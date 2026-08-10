import json
import logging
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.session import Session
from app.repositories.sessions import SessionRepository
from app.schemas.model_request_snapshot import (
    ModelRequestBlocks,
    ModelRequestMessage,
    ModelRequestPrivacy,
    ModelRequestSnapshot,
    ModelTransportSnapshot,
)
from app.schemas.teaching import TeachingContext, TeachingOutput
from app.services.ai_evaluation import AIModelClient, AITransportError

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "generate_teaching.md"
logger = logging.getLogger(__name__)


class AITeachingError(RuntimeError):
    def __init__(self, *, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


class AITeachingService:
    def __init__(self, database_session: DatabaseSession, settings: Settings) -> None:
        self.repository = SessionRepository(database_session)
        self.settings = settings
        self.client = AIModelClient(settings)

    def generate(self, *, session: Session, context: TeachingContext) -> TeachingOutput:
        request = _render_prompt(
            context,
            model=self.settings.ai_model,
            prompt_version=self.settings.prompt_version,
        )
        try:
            model_response = self.client.evaluate(request)
        except AITransportError as error:
            self.repository.record_external_call(
                session=session,
                call_type="AI_TEACHING",
                attempt_number=1,
                transport_status="ERROR",
                duration_ms=error.duration_ms,
                provider=self.settings.ai_provider,
                model=self.settings.ai_model,
                error_type=error.error_type,
                error_message=str(error),
                raw_response=error.raw_response,
                request_snapshot=request,
            )
            logger.error(
                "AI 教学调用失败",
                extra={
                    "eventName": "ai.call.failed",
                    "purpose": request.purpose,
                    "model": self.settings.ai_model,
                    "durationMs": error.duration_ms,
                    "errorType": error.error_type,
                },
            )
            raise AITeachingError(error_type=error.error_type, message=str(error)) from error

        external_call = self.repository.record_external_call(
            session=session,
            call_type="AI_TEACHING",
            attempt_number=1,
            transport_status="SUCCESS",
            duration_ms=model_response.duration_ms,
            provider=self.settings.ai_provider,
            model=self.settings.ai_model,
            raw_response=model_response.raw_response,
            request_snapshot=request,
        )
        logger.info(
            "AI 教学调用完成",
            extra={
                "eventName": "ai.call.completed",
                "purpose": request.purpose,
                "model": self.settings.ai_model,
                "durationMs": model_response.duration_ms,
            },
        )

        try:
            output = TeachingOutput.model_validate_json(model_response.content)
            validation_errors = validate_teaching_output(output=output, context=context)
            if validation_errors:
                raise ValueError("；".join(validation_errors))
        except (ValidationError, ValueError) as error:
            errors = (
                [entry["msg"] for entry in error.errors()]
                if isinstance(error, ValidationError)
                else [str(error)]
            )
            message = "；".join(errors)
            self.repository.record_external_call_validation(
                record=external_call,
                validation_status="INVALID",
                validation_errors=errors,
            )
            logger.error(
                "AI 教学输出校验失败",
                extra={
                    "eventName": "ai.output.validation_failed",
                    "purpose": request.purpose,
                    "model": self.settings.ai_model,
                    "durationMs": model_response.duration_ms,
                    "errorType": "AI_SCHEMA_ERROR",
                },
            )
            raise AITeachingError(error_type="AI_SCHEMA_ERROR", message=message) from error

        self.repository.record_external_call_validation(
            record=external_call,
            validation_status="VALID",
            validation_errors=[],
        )
        logger.info(
            "AI 教学输出校验通过",
            extra={
                "eventName": "ai.output.validated",
                "purpose": request.purpose,
                "model": self.settings.ai_model,
                "durationMs": model_response.duration_ms,
            },
        )
        return output


def validate_teaching_output(
    *, output: TeachingOutput, context: TeachingContext
) -> list[str]:
    errors: list[str] = []
    action = context.instruction_from_rules.allowed_action
    expected_question_count = 1 if action in {"ASK_FOCUSED_QUESTION", "CORRECT_AND_ASK"} else 0
    if len(output.questions) != expected_question_count:
        errors.append(f"{action} 要求 questions 数量为 {expected_question_count}")

    combined_output = "\n".join(
        [output.content, *(question.question for question in output.questions)]
    )
    if context.task.full_solution in combined_output:
        errors.append("教学输出不得直接包含完整解析")
    if context.task.standard_answer in combined_output:
        errors.append("教学输出不得直接包含标准答案")

    normalized_content = _normalize(output.content)
    prior_contents = {_normalize(item) for item in context.instruction_from_rules.do_not_repeat}
    if normalized_content in prior_contents:
        errors.append("教学输出不得完全重复已发送支持")
    return errors


def _render_prompt(
    context: TeachingContext, *, model: str, prompt_version: str
) -> ModelRequestSnapshot:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        template
        .replace(
            "{{JSON_SCHEMA}}",
            json.dumps(TeachingOutput.model_json_schema(by_alias=True), ensure_ascii=False),
        )
        .replace(
            "{{CONTEXT_JSON}}",
            context.model_dump_json(by_alias=True),
        )
    )
    task = context.task.model_dump(mode="json", by_alias=True)
    current_student_text = task.pop("currentStudentText")
    session_context = {
        "latestEvaluation": context.latest_evaluation.model_dump(mode="json", by_alias=True),
        "learningProgress": context.learning_progress.model_dump(mode="json", by_alias=True),
        "teachingHistory": context.teaching_history.model_dump(mode="json", by_alias=True),
        "teachingMetadata": context.teaching_metadata.model_dump(mode="json", by_alias=True),
        "instructionFromRules": context.instruction_from_rules.model_dump(
            mode="json", by_alias=True
        ),
    }
    return ModelRequestSnapshot(
        purpose="AI_SUPPORT",
        prompt_version=prompt_version,
        blocks=ModelRequestBlocks(
            system_instructions=template,
            question_context=task,
            session_context=session_context,
            user_input={"currentStudentText": current_student_text},
            retry_context={"validationErrors": []},
        ),
        transport=ModelTransportSnapshot(
            model=model,
            messages=[ModelRequestMessage(role="user", content=prompt)],
            response_format={"type": "json_object"},
        ),
        privacy=ModelRequestPrivacy(
            contains_student_content=True,
            contains_answer_material=True,
            contains_memory=False,
        ),
    )


def _normalize(value: str) -> str:
    return " ".join(value.split())
