import re
from html.parser import HTMLParser

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.auth import CurrentUser, DatabaseSession
from app.models.question import Question
from app.models.session import Session
from app.models.tts_voice import TTSSpeechSettings, TTSVoice
from app.repositories.sessions import SessionRepository
from app.services.teacher_speech import TeacherSpeechError

router = APIRouter(prefix="/sessions", tags=["teacher-speech"])
SPEECH_EVENT_TYPES = {"SUPPORT", "GUIDED_QUESTIONS", "FOLLOW_UP", "MASTERY_QUESTIONS"}
TEACHING_ACTIONS = {"ASK_FOCUSED_QUESTION", "GIVE_HINT", "GIVE_CORRECTION", "CORRECT_AND_ASK"}


class TeacherSpeechInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_ids: list[str] = Field(default_factory=list, alias="itemIds", max_length=30)
    full_solution: bool = Field(default=False, alias="fullSolution")

    @model_validator(mode="after")
    def validate_source(self):
        if bool(self.item_ids) == self.full_solution:
            raise ValueError("请选择教师回复或完整解析其中一种朗读来源")
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("朗读记录 ID 不能重复")
        return self


class SolutionTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.ignored += 1
        elif not self.ignored:
            if tag == "img":
                attributes = dict(attrs)
                text = attributes.get("data-latex") or attributes.get("alt")
                if not text or text.strip() in {"图片", "公式", "image"}:
                    raise HTTPException(422, "完整解析包含缺少可朗读文字的图片，请阅读文字解析")
                self.parts.append(text)
            elif tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
                self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1
        elif not self.ignored and tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)


def solution_speech_text(solution: str) -> str:
    # 只解析实际 HTML 标记，避免把纯文本数学比较 a<b 当作 HTML 删除。
    if re.search(
        r"</?(?:p|div|span|br|img|li|ul|ol|table|tr|td|math|script|style|strong|em|h[1-6])\b",
        solution,
        re.IGNORECASE,
    ):
        parser = SolutionTextParser()
        parser.feed(solution)
        text = "".join(parser.parts).strip()
    else:
        text = solution.strip()
    if not text:
        raise HTTPException(422, "完整解析没有可朗读的文字")
    return text


@router.post("/{session_id}/teacher-speech", response_class=FileResponse)
def synthesize_teacher_speech(
    session_id: int,
    speech_input: TeacherSpeechInput,
    request: Request,
    database_session: DatabaseSession,
    current_user: CurrentUser,
) -> FileResponse:
    session = database_session.get(Session, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(404, "会话不存在")
    timeline = SessionRepository(database_session).get_student_timeline(session_id)
    if speech_input.full_solution:
        if not session.solution_exposed and not any(
            item["event_type"] == "FULL_SOLUTION" for item in timeline
        ):
            raise HTTPException(403, "当前会话尚未展示完整解析")
        question = database_session.get(Question, session.question_id)
        if question is None or not question.full_solution:
            raise HTTPException(422, "本题没有可朗读的完整解析")
        text = solution_speech_text(question.full_solution)
    else:
        requested = set(speech_input.item_ids)
        items = [item for item in timeline if item["id"] in requested]
        if len(items) != len(requested):
            raise HTTPException(404, "请求的教师回复记录不存在")
        for item in items:
            eligible = item["event_type"] in SPEECH_EVENT_TYPES or (
                item["event_type"] == "EVALUATION" and item["action"] in TEACHING_ACTIONS
            )
            if item["speaker"] != "AI" or not eligible:
                raise HTTPException(422, "请求的记录不属于可朗读的教师回复")
        text = "\n".join(str(item["content"]) for item in items)
    try:
        selection = database_session.get(TTSSpeechSettings, current_user.id)
        if selection is None or selection.voice_id is None:
            raise TeacherSpeechError(
                "TTS_VOICE_NOT_SELECTED", "尚未选择教师音色，请在设置中选择", 503
            )
        voice = database_session.get(TTSVoice, selection.voice_id)
        if voice is None:
            raise TeacherSpeechError("TTS_VOICE_MISSING", "当前教师音色记录不存在", 503)
        path = request.app.state.teacher_speech_service.synthesize(text, voice)
    except TeacherSpeechError as error:
        raise HTTPException(
            error.status_code, {"code": error.code, "message": str(error)}
        ) from error
    return FileResponse(
        path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"}
    )
