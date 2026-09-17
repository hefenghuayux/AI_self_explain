import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.ai_evaluation import AIEvaluation
from app.models.explanation_attempt import ExplanationAttempt
from app.models.external_call_record import ExternalCallRecord
from app.models.question import Question
from app.models.session import Session
from app.models.support_event import SupportEvent
from app.repositories.sessions import SessionRepository, session_run_id
from app.schemas.ai_evaluation import (
    AIEvaluationOutput,
    evaluation_json_schema,
    validate_evaluation_relationships,
)
from app.schemas.model_request_snapshot import (
    ModelRequestBlocks,
    ModelRequestMessage,
    ModelRequestPrivacy,
    ModelRequestSnapshot,
    ModelTransportSnapshot,
)
from app.services.ai_reasoning import resolve_reasoning_params
from app.services.session_event_log import SessionEventLog

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "evaluate_explanation.md"
SHARED_SYSTEM_PATH = Path(__file__).resolve().parents[1] / "prompts" / "shared_system.md"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIModelResponse:
    raw_response: str
    content: str
    duration_ms: int


@dataclass(frozen=True)
class EvaluationResult:
    evaluation_record: AIEvaluation
    output: AIEvaluationOutput


class AITransportError(RuntimeError):
    def __init__(
        self,
        *,
        error_type: str,
        message: str,
        duration_ms: int,
        raw_response: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.duration_ms = duration_ms
        self.raw_response = raw_response


class AIModelClient:
    def __init__(self, settings: Settings, http_client: httpx.Client) -> None:
        self.settings = settings
        self.http_client = http_client

    def evaluate(self, request: ModelRequestSnapshot) -> AIModelResponse:
        started_at = time.perf_counter()
        endpoint = f"{str(self.settings.ai_base_url).rstrip('/')}/chat/completions"
        try:
            response = self.http_client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.settings.ai_api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                # DeepSeek 当前只支持 JSON object 模式。动态 Schema 仍在提示词和
                # 本地校验中严格执行；这里直接发送审计快照中的真实 transport。
                json=request.transport_payload(),
            )
        except httpx.TimeoutException as error:
            raise AITransportError(
                error_type="AI_TIMEOUT",
                message=f"AI 请求超时：{error}",
                duration_ms=_duration_ms(started_at),
            ) from error
        except httpx.RequestError as error:
            raise AITransportError(
                error_type="AI_SERVICE_ERROR",
                message=f"AI 服务请求失败：{error}",
                duration_ms=_duration_ms(started_at),
            ) from error

        raw_response = response.text
        if response.is_error:
            raise AITransportError(
                error_type="AI_SERVICE_ERROR",
                message=f"AI 服务返回 HTTP {response.status_code}",
                duration_ms=_duration_ms(started_at),
                raw_response=raw_response,
            )
        try:
            response_body = response.json()
            content = response_body["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise AITransportError(
                error_type="AI_SERVICE_ERROR",
                message=f"AI 服务响应不包含可解析的 choices[0].message.content：{error}",
                duration_ms=_duration_ms(started_at),
                raw_response=raw_response,
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise AITransportError(
                error_type="AI_SERVICE_ERROR",
                message="AI 服务响应中的 choices[0].message.content 不能为空字符串",
                duration_ms=_duration_ms(started_at),
                raw_response=raw_response,
            )
        return AIModelResponse(
            raw_response=raw_response,
            content=content,
            duration_ms=_duration_ms(started_at),
        )


class AIEvaluationService:
    def __init__(
        self, database_session: DatabaseSession, settings: Settings, http_client: httpx.Client
    ) -> None:
        self.repository = SessionRepository(database_session)
        self.settings = settings
        self.client = AIModelClient(settings, http_client)

    def evaluate(
        self,
        *,
        question: Question,
        session: Session,
        attempt: ExplanationAttempt,
    ) -> EvaluationResult | Session:
        rubric_points = question.rubric_points or []
        evaluation_mode = question.evaluation_mode
        schema = evaluation_json_schema(rubric_points)
        validation_errors: list[str] = []
        previous_output: str | None = None
        external_attempt_number = 0
        run_id = session_run_id(session.id, attempt.id)
        event_log = SessionEventLog(self.repository.database_session)

        previous_attempts = self.repository.database_session.scalars(
            select(ExplanationAttempt)
            .where(
                ExplanationAttempt.session_id == session.id,
                ExplanationAttempt.round == session.round,
                ExplanationAttempt.id < attempt.id,
                ExplanationAttempt.id.in_(select(AIEvaluation.attempt_id)),
            )
            .order_by(ExplanationAttempt.id)
        ).all()
        previous_support = self.repository.database_session.scalars(
            select(SupportEvent)
            .where(SupportEvent.session_id == session.id, SupportEvent.round == session.round)
            .order_by(SupportEvent.id)
        ).all()
        progress_context = build_progress_context(
            previous_attempts=previous_attempts,
            previous_support=previous_support,
            max_interactions=self.settings.progress_context_max_interactions,
        )

        for schema_attempt in range(self.settings.ai_schema_max_retries + 1):
            reasoning_effort = self.settings.ai_reasoning_effort
            request = _render_prompt(
                question=question,
                session=session,
                attempt=attempt,
                schema=schema,
                validation_errors=validation_errors,
                model=self.settings.ai_model,
                prompt_version=self.settings.prompt_version,
                reasoning_effort=reasoning_effort,
                progress_context=progress_context,
                previous_output=previous_output,
            )
            if schema_attempt == 0:
                event_log.append_contexts(
                    session_id=session.id,
                    run_id=run_id,
                    request=request,
                    question_source=f"question:{question.id}",
                    parent_event_id=event_log.latest_event_id(session.id, run_id),
                )
            model_response, external_call, external_attempt_number, requested_event_id = (
                self._call_with_transport_retries(
                    session=session,
                    request=request,
                    external_attempt_number=external_attempt_number,
                    run_id=run_id,
                )
            )
            if model_response is None:
                return self.repository.request_human_review(
                    session=session,
                    need_human_reason="AI 评价服务在配置的重试次数内未成功响应",
                    trigger_type="AI_EVALUATION_TRANSPORT_RETRY_EXHAUSTED",
                    related_attempt_id=attempt.id,
                    run_id=run_id,
                )

            if external_call is None:
                raise RuntimeError("AI 评价传输成功后缺少外部调用记录")
            evaluation_output, validation_errors = _parse_and_validate_evaluation(
                model_response.content,
                rubric_points,
                attempt.confirmed_text,
            )
            if validation_errors:
                previous_output = model_response.content
                event_log.append_model_responded(
                    session_id=session.id,
                    run_id=run_id,
                    response_content=model_response.content,
                    validation="invalid",
                    duration_ms=model_response.duration_ms,
                    parent_event_id=requested_event_id,
                )
                self.repository.record_external_call_validation(
                    record=external_call,
                    validation_status="INVALID",
                    validation_errors=validation_errors,
                )
                logger.log(
                    logging.ERROR
                    if schema_attempt == self.settings.ai_schema_max_retries
                    else logging.WARNING,
                    "AI 评价输出校验失败",
                    extra={
                        "eventName": "ai.output.validation_failed",
                        "purpose": request.purpose,
                        "model": self.settings.ai_model,
                        "durationMs": model_response.duration_ms,
                        "errorType": "AI_SCHEMA_ERROR",
                    },
                )
                invalid_evaluation = self.repository.record_invalid_evaluation(
                    session=session,
                    attempt=attempt,
                    evaluation=evaluation_output,
                    raw_response=model_response.raw_response,
                    validation_errors=validation_errors,
                    request_duration_ms=model_response.duration_ms,
                    prompt_version=self.settings.prompt_version,
                    model_provider=self.settings.ai_provider,
                    model_name=self.settings.ai_model,
                    external_call_record_id=external_call.id,
                    evaluation_mode=evaluation_mode,
                )
                if schema_attempt == self.settings.ai_schema_max_retries:
                    reason = "AI 结构化评价在配置的重试次数内仍不合法：" + "；".join(
                        validation_errors
                    )
                    return self.repository.request_human_review(
                        session=session,
                        need_human_reason=reason,
                        trigger_type="AI_EVALUATION_SCHEMA_RETRY_EXHAUSTED",
                        related_attempt_id=attempt.id,
                        related_evaluation_id=invalid_evaluation.id,
                    )
                continue

            if evaluation_output is None:
                raise RuntimeError("AI 评价校验完成后缺少评价结果")
            self.repository.record_external_call_validation(
                record=external_call,
                validation_status="VALID",
                validation_errors=[],
            )
            event_log.append_model_responded(
                session_id=session.id,
                run_id=run_id,
                response_content=model_response.content,
                validation="valid",
                duration_ms=model_response.duration_ms,
                parent_event_id=requested_event_id,
            )
            logger.info(
                "AI 评价输出校验通过",
                extra={
                    "eventName": "ai.output.validated",
                    "purpose": request.purpose,
                    "model": self.settings.ai_model,
                    "durationMs": model_response.duration_ms,
                },
            )
            saved_evaluation = self.repository.record_valid_evaluation(
                session=session,
                attempt=attempt,
                evaluation=evaluation_output,
                raw_response=model_response.raw_response,
                request_duration_ms=model_response.duration_ms,
                prompt_version=self.settings.prompt_version,
                model_provider=self.settings.ai_provider,
                model_name=self.settings.ai_model,
                external_call_record_id=external_call.id,
                evaluation_mode=evaluation_mode,
            )
            return EvaluationResult(
                evaluation_record=saved_evaluation,
                output=evaluation_output,
            )
        raise RuntimeError("AI 结构化评价循环未产生结果")

    def _call_with_transport_retries(
        self,
        *,
        session: Session,
        request: ModelRequestSnapshot,
        external_attempt_number: int,
        run_id: str,
    ) -> tuple[AIModelResponse | None, ExternalCallRecord | None, int, str | None]:
        event_log = SessionEventLog(self.repository.database_session)
        for transport_attempt in range(self.settings.ai_transport_max_retries + 1):
            current_attempt_number = external_attempt_number + 1
            requested_event = event_log.append_model_requested(
                session_id=session.id,
                run_id=run_id,
                request=request,
                provider=self.settings.ai_provider,
                parent_event_id=event_log.latest_event_id(session.id, run_id),
            )
            try:
                model_response = self.client.evaluate(request)
            except AITransportError as error:
                self.repository.record_external_call(
                    session=session,
                    attempt_number=current_attempt_number,
                    transport_status="ERROR",
                    duration_ms=error.duration_ms,
                    provider=self.settings.ai_provider,
                    model=self.settings.ai_model,
                    error_type=error.error_type,
                    error_message=str(error),
                    raw_response=error.raw_response,
                    request_snapshot=request,
                )
                event_log.append_model_failed(
                    session_id=session.id,
                    run_id=run_id,
                    error_type=error.error_type,
                    message=str(error),
                    duration_ms=error.duration_ms,
                    parent_event_id=requested_event.event_id,
                )
                logger.log(
                    logging.ERROR
                    if transport_attempt == self.settings.ai_transport_max_retries
                    else logging.WARNING,
                    "AI 评价调用失败",
                    extra={
                        "eventName": "ai.call.failed",
                        "purpose": request.purpose,
                        "model": self.settings.ai_model,
                        "durationMs": error.duration_ms,
                        "errorType": error.error_type,
                    },
                )
                if transport_attempt == self.settings.ai_transport_max_retries:
                    return None, None, current_attempt_number, requested_event.event_id
                time.sleep(self.settings.ai_retry_backoff_seconds[transport_attempt])
                external_attempt_number = current_attempt_number
                continue

            external_call = self.repository.record_external_call(
                session=session,
                attempt_number=current_attempt_number,
                transport_status="SUCCESS",
                duration_ms=model_response.duration_ms,
                provider=self.settings.ai_provider,
                model=self.settings.ai_model,
                raw_response=model_response.raw_response,
                request_snapshot=request,
            )
            logger.info(
                "AI 评价调用完成",
                extra={
                    "eventName": "ai.call.completed",
                    "purpose": request.purpose,
                    "model": self.settings.ai_model,
                    "durationMs": model_response.duration_ms,
                },
            )
            return model_response, external_call, current_attempt_number, requested_event.event_id
        raise RuntimeError("AI 传输重试循环未产生结果")


def _append_support_events(
    events: list[dict[str, object]], support: SupportEvent, seq_start: int
) -> int:
    """把一个 SupportEvent 展开为带 role 的事件并追加到 events。

    最多生成 4 个事件：teaching、guided_answer（每条回答一个）、follow_up。
    返回下一个可用 seq。
    """
    interaction_id = f"support:{support.id}"
    next_seq = seq_start
    question_by_id = {
        str(question.get("id", "")): str(question.get("question", ""))
        for question in support.guided_questions or []
        if isinstance(question, dict)
    }
    content_parts = [support.content]
    for question in support.guided_questions or []:
        if isinstance(question, dict) and question.get("question"):
            content_parts.append(f"问：{question['question']}")
    events.append(
        {
            "seq": next_seq,
            "actor": "teacher",
            "kind": "teaching",
            "content": "\n\n".join(content_parts),
            "interactionId": interaction_id,
        }
    )
    next_seq += 1
    for answer in support.guided_answers or []:
        if not isinstance(answer, dict):
            continue
        answer_id = str(answer.get("question_id", ""))
        events.append(
            {
                "seq": next_seq,
                "actor": "student",
                "kind": "guided_answer",
                "content": [
                    {
                        "questionId": answer_id,
                        "question": question_by_id.get(answer_id, ""),
                        "answer": str(answer.get("answer", "")),
                    }
                ],
                "interactionId": interaction_id,
                "replyTo": interaction_id,
            }
        )
        next_seq += 1
    if support.follow_up_content:
        events.append(
            {
                "seq": next_seq,
                "actor": "teacher",
                "kind": "follow_up",
                "content": support.follow_up_content,
                "interactionId": f"{interaction_id}:followup",
            }
        )
        next_seq += 1
    return next_seq


def build_progress_context(
    *,
    previous_attempts: list[ExplanationAttempt],
    previous_support: list[SupportEvent],
    max_interactions: int,
) -> dict[str, list[dict[str, object]]]:
    """把同 round 的学生自讲与教学事件合并成带 role 的有序事件序列。

    阶段一实现：不读取 session_events，直接从现有表查询结果按
    （created_at, id）排序，id 作为同一时间戳下的稳定回退顺序。
    截断按交互组执行，见 _truncate_by_interaction。
    """
    raw: list[tuple[object, int, str, object]] = []
    for item in previous_attempts:
        if item.confirmed_text:
            raw.append((item.created_at, item.id, "attempt", item))
    for item in previous_support:
        raw.append((item.created_at, item.id, "support", item))
    raw.sort(key=lambda entry: (entry[0], entry[1]))

    events: list[dict[str, object]] = []
    next_seq = 0
    for _, _, rec_type, record in raw:
        if rec_type == "attempt":
            events.append(
                {
                    "seq": next_seq,
                    "actor": "student",
                    "kind": "explanation",
                    "content": record.confirmed_text,
                    "interactionId": f"attempt:{record.id}",
                }
            )
            next_seq += 1
        else:
            next_seq = _append_support_events(events, record, next_seq)
    return {"events": _truncate_by_interaction(events, max_interactions)}


def _truncate_by_interaction(
    events: list[dict[str, object]], max_interactions: int
) -> list[dict[str, object]]:
    """从序列尾部按完整交互组保留，保证不拆散问答。

    交互组边界：
    - teaching 总是开启一个新的教学回合；其后的 guided_answer 与
      follow_up 属于同一回合，直到下一条 explanation 或新的 teaching 关闭它。
    - explanation 自成一组（一轮自讲）。
    - 孤立 guided_answer（防御性兜底）并入当前回合或自成一组的最后一个位置。
    """
    if max_interactions <= 0 or not events:
        return []

    groups: list[int] = []
    group_id = 0
    in_exchange = False
    for event in events:
        actor = event.get("actor")
        kind = event.get("kind")
        if actor == "teacher" and kind == "teaching":
            group_id += 1
            in_exchange = True
        elif actor == "teacher" and kind == "follow_up":
            if not in_exchange:
                group_id += 1
            in_exchange = True
        elif actor == "student" and kind == "guided_answer":
            if not in_exchange:
                group_id += 1
            in_exchange = True
        elif actor == "student" and kind == "explanation":
            group_id += 1
            in_exchange = False
        groups.append(group_id)

    max_group = max(groups)
    keep_threshold = max(0, max_group - max_interactions + 1)
    return [
        event
        for event, group in zip(events, groups)
        if group >= keep_threshold
    ]


def _render_prompt(
    *,
    question: Question,
    session: Session,
    attempt: ExplanationAttempt,
    schema: dict[str, object],
    validation_errors: list[str],
    model: str,
    prompt_version: str,
    reasoning_effort: str | None = None,
    progress_context: dict[str, object] | None = None,
    previous_output: str | None = None,
) -> ModelRequestSnapshot:
    shared_system = SHARED_SYSTEM_PATH.read_text(encoding="utf-8")
    template = PROMPT_PATH.read_text(encoding="utf-8")
    question_context: dict[str, object] = {
        "questionContent": question.question_content,
        "standardAnswer": question.standard_answer,
        "evaluationMode": question.evaluation_mode,
        "rubricPoints": question.rubric_points or [],
        "commonErrors": question.common_errors,
        "alternativeSolutions": question.alternative_solutions,
        "layeredHints": question.layered_hints,
        "guidedQuestions": question.guided_questions,
        "fullSolution": question.full_solution,
        "outputSchema": schema,
    }
    user_input: dict[str, object] = {
        "confirmedText": attempt.confirmed_text,
    }
    # 五层消息
    # messages[0] system：全局共享前缀
    # messages[1] user：会话级稳定上下文（题目数据，不含 outputSchema）
    question_message: dict[str, object] = {
        key: value
        for key, value in question_context.items()
        if key != "outputSchema"
    }
    # messages[2] user：截至当前任务前的共享历史
    session_history = progress_context or {"events": []}
    # messages[3] user：taskType 固定指令 + JSON Schema
    task_prompt = template.replace(
        "{{JSON_SCHEMA}}", json.dumps(schema, ensure_ascii=False)
    )
    # messages[4] user：本轮任务数据
    current_data: dict[str, object] = {
        "confirmedText": attempt.confirmed_text,
    }
    if validation_errors:
        current_data["previousOutput"] = previous_output
        current_data["validationErrors"] = validation_errors
    elif previous_output is not None:
        current_data["previousOutput"] = previous_output
        current_data["validationErrors"] = []
    extra_body = resolve_reasoning_params(model, reasoning_effort)
    return ModelRequestSnapshot(
        schema_version="1.1",
        purpose="AI_EVALUATION",
        prompt_version=prompt_version,
        blocks=ModelRequestBlocks(
            system_instructions=shared_system,
            task_instructions=task_prompt,
            question_context=question_context,
            session_context={
                "taskType": "EXPLANATION",
                "progressContext": session_history,
                "round": session.round,
                "supportCountRound": session.support_count_round,
            },
            user_input=user_input,
            retry_context={
                "validationErrors": validation_errors,
                "previousOutput": previous_output,
            },
        ),
        transport=ModelTransportSnapshot(
            model=model,
            messages=[
                ModelRequestMessage(role="system", content=shared_system),
                ModelRequestMessage(
                    role="user",
                    content=json.dumps(question_message, ensure_ascii=False),
                ),
                ModelRequestMessage(
                    role="user",
                    content=json.dumps(session_history, ensure_ascii=False),
                ),
                ModelRequestMessage(role="user", content=task_prompt),
                ModelRequestMessage(
                    role="user",
                    content=json.dumps(current_data, ensure_ascii=False),
                ),
            ],
            response_format={"type": "json_object"},
            reasoning_effort=reasoning_effort,
            extra_body=extra_body,
        ),
        privacy=ModelRequestPrivacy(
            contains_student_content=True,
            contains_answer_material=True,
            contains_memory=False,
        ),
    )


def _parse_and_validate_evaluation(
    content: str,
    rubric_points: list[str],
    confirmed_text: str,
) -> tuple[AIEvaluationOutput | None, list[str]]:
    try:
        payload = json.loads(content)
        if isinstance(payload, dict):
            payload.pop("coveredPoints", None)
            payload.pop("errorEvidence", None)
        evaluation = AIEvaluationOutput.model_validate(payload)
    except (ValidationError, ValueError, TypeError) as error:
        if isinstance(error, ValidationError):
            return None, [entry["msg"] for entry in error.errors()]
        return None, [str(error)]
    return evaluation, validate_evaluation_relationships(evaluation)


def _duration_ms(started_at: float) -> int:
    return round((time.perf_counter() - started_at) * 1000)
