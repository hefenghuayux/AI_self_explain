import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.models.explanation_attempt import ExplanationAttempt  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.session import Session  # noqa: E402
from app.rules.teaching_decision import decide_teaching  # noqa: E402
from app.schemas.ai_evaluation import AIEvaluationOutput  # noqa: E402
from app.schemas.teaching import TeachingOutput  # noqa: E402
from app.services import ai_teaching  # noqa: E402
from app.services.ai_evaluation import AIModelResponse  # noqa: E402
from app.services.ai_teaching import AITeachingService  # noqa: E402

RUBRIC_POINTS = ["说明加法", "得到结果 2"]


def evaluation(
    *,
    correctness: str = "CORRECT",
    completeness: str = "INCOMPLETE",
    has_progress: bool = True,
) -> AIEvaluationOutput:
    terminal = correctness == "CORRECT" and completeness == "COMPLETE"
    return AIEvaluationOutput.model_validate(
        {
            "correctness": correctness,
            "completeness": completeness,
            "coveredPoints": [1],
            "errorEvidence": [],
            "hasProgress": has_progress,
            "mainReason": None if terminal else "知识应用问题",
            "otherReasons": [],
            "judgeReason": None if terminal else "学生尚未给出最终结果。",
        }
    )


def current_session(**updates: object) -> Session:
    values = {
        "id": 1,
        "round": 1,
        "support_count_round": 0,
        "support_count_total": 0,
        "no_progress_count": 0,
        "no_progress_help_request_count": 0,
        "solution_exposed": False,
        "covered_points_current_round": [],
        "covered_points_all": [],
    }
    values.update(updates)
    return Session(**values)


def settings(**updates: object) -> SimpleNamespace:
    values = {
        "first_round_support_limit": 6,
        "second_round_support_limit": 3,
        "ai_schema_max_retries": 1,
        "ai_transport_max_retries": 0,
        "ai_retry_backoff_seconds": [],
        "ai_model": "test-model",
        "ai_provider": "test-provider",
        "prompt_version": "test-v1",
        "ai_reasoning_effort": None,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_stage_schemas_reject_each_others_fields() -> None:
    evaluation_payload = evaluation().model_dump(mode="json", by_alias=True)
    evaluation_payload["content"] = "不应出现"
    with pytest.raises(ValidationError):
        AIEvaluationOutput.model_validate(evaluation_payload)

    with pytest.raises(ValidationError):
        TeachingOutput.model_validate(
            {
                "content": "请继续说明。",
                "questions": [],
                "mainReason": "知识应用问题",
            }
        )


@pytest.mark.parametrize(
    ("result", "expected_action"),
    [
        (evaluation(has_progress=False), "GIVE_HINT"),
        (evaluation(correctness="WRONG"), "GIVE_CORRECTION"),
        (evaluation(), "ASK_FOCUSED_QUESTION"),
    ],
)
def test_backend_selects_action_from_evaluation(
    result: AIEvaluationOutput, expected_action: str
) -> None:
    decision = decide_teaching(
        evaluation=result,
        session=current_session(),
        settings=settings(),
        rubric_points=RUBRIC_POINTS,
    )

    assert decision.allowed_action == expected_action
    assert decision.should_generate is True


def test_complete_and_support_limit_skip_teaching() -> None:
    completed = decide_teaching(
        evaluation=evaluation(completeness="COMPLETE"),
        session=current_session(),
        settings=settings(),
        rubric_points=RUBRIC_POINTS,
    )
    limited = decide_teaching(
        evaluation=evaluation(correctness="WRONG"),
        session=current_session(support_count_round=5),
        settings=settings(),
        rubric_points=RUBRIC_POINTS,
    )

    assert completed.next_status == "COMPLETED"
    assert completed.should_generate is False
    assert limited.expose_solution is True
    assert limited.should_generate is False


class FakeEventLog:
    def __init__(self, database_session) -> None:
        pass

    def latest_event_id(self, session_id: int, run_id: str) -> None:
        return None

    def append_contexts(self, **kwargs) -> None:
        return None

    def append_model_requested(self, **kwargs) -> SimpleNamespace:
        return SimpleNamespace(event_id="request-event")

    def append_model_responded(self, **kwargs) -> None:
        return None

    def append_model_failed(self, **kwargs) -> None:
        return None


def teaching_service(monkeypatch, responses: list[str]) -> AITeachingService:
    database_session = Mock()
    database_session.scalars.return_value = []
    service = AITeachingService(database_session, settings(), Mock())
    service.repository.record_external_call = Mock(return_value=SimpleNamespace(id=1))
    service.repository.record_external_call_validation = Mock()
    calls = iter(responses)
    service.client.evaluate = lambda request: AIModelResponse(
        raw_response="{}", content=next(calls), duration_ms=1
    )
    monkeypatch.setattr(ai_teaching, "SessionEventLog", FakeEventLog)
    return service


def generate(service: AITeachingService):
    result = evaluation()
    session = current_session()
    decision = decide_teaching(
        evaluation=result,
        session=session,
        settings=settings(),
        rubric_points=RUBRIC_POINTS,
    )
    return service.generate(
        question=Question(
            id=1,
            question_content="计算 1 + 1。",
            standard_answer="2",
            rubric_points=RUBRIC_POINTS,
            full_solution="1 加 1 等于 2。",
        ),
        session=session,
        attempt=ExplanationAttempt(id=1, confirmed_text="我先做加法。"),
        evaluation=result,
        decision=decision,
    )


def test_invalid_teaching_output_retries_only_teaching(monkeypatch) -> None:
    service = teaching_service(
        monkeypatch,
        [
            json.dumps({"content": "请继续。", "questions": []}),
            json.dumps(
                {
                    "content": "请补充最后一步。",
                    "questions": [{"id": "q1", "question": "最后结果是多少？"}],
                },
                ensure_ascii=False,
            ),
        ],
    )

    output = generate(service)

    assert output is not None
    assert output.questions[0].id == "q1"
    calls = service.repository.record_external_call.call_args_list
    assert len(calls) == 2
    assert all(call.kwargs["call_type"] == "AI_TEACHING" for call in calls)
    second_request = calls[1].kwargs["request_snapshot"]
    assert second_request.blocks.retry_context["previousOutput"]
    assert second_request.blocks.retry_context["validationErrors"]


def test_teaching_retry_exhaustion_returns_no_output(monkeypatch) -> None:
    invalid = json.dumps({"content": "请继续。", "questions": []})
    service = teaching_service(monkeypatch, [invalid, invalid])

    output = generate(service)

    assert output is None
    assert service.repository.record_external_call.call_count == 2
