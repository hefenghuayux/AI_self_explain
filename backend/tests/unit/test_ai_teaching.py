import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.models.session import Session
from app.schemas.teaching import TeachingContext, TeachingOutput
from app.services.ai_evaluation import AIModelResponse, AITransportError
from app.services.ai_teaching import AITeachingError, AITeachingService, validate_teaching_output


def teaching_context(action: str = "ASK_FOCUSED_QUESTION") -> TeachingContext:
    return TeachingContext.model_validate(
        {
            "task": {
                "questionContent": "1+1 等于多少？",
                "standardAnswer": "标准答案是二",
                "rubricPoints": ["说明加法", "得到结果二"],
                "commonErrors": ["结果写成三"],
                "alternativeSolutions": [],
                "layeredHints": ["想一想两个一"],
                "guidedQuestions": [],
                "fullSolution": "完整解析为一加一等于二",
                "currentStudentText": "两个一相加。",
            },
            "latestEvaluation": {
                "correctness": "CORRECT",
                "completeness": "INCOMPLETE",
                "coveredPoints": ["说明加法"],
                "missingPoints": ["得到结果二"],
                "errorEvidence": [],
            },
            "learningProgress": {
                "alreadyCoveredPoints": ["说明加法"],
                "newlyCoveredPoints": [],
                "targetRubricPoint": "得到结果二",
                "targetErrorEvidence": None,
            },
            "teachingHistory": {
                "recentAttempts": [],
                "alreadyGivenSupports": [],
                "historyTruncated": False,
            },
            "teachingMetadata": {
                "learningPhase": "FIRST_ROUND",
                "supportBudgetState": "EARLY",
                "progressState": "NO_NEW_PROGRESS",
                "solutionExposure": "FORBIDDEN",
            },
            "instructionFromRules": {
                "allowedAction": action,
                "targetRubricPoint": "得到结果二",
                "doNotRepeat": ["请说出最后结果。"],
                "doNotReveal": ["DO_NOT_REVEAL_FULL_SOLUTION"],
                "responseGoal": "ASK_ONE_FOCUSED_QUESTION",
            },
            "longTermEvidence": None,
        }
    )


def test_teaching_output_rejects_wrong_question_count() -> None:
    output = TeachingOutput(content="请继续思考。", questions=[])

    errors = validate_teaching_output(output=output, context=teaching_context())

    assert errors == ["ASK_FOCUSED_QUESTION 要求 questions 数量为 1"]


@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        ("完整解析为一加一等于二", "不得直接包含完整解析"),
        ("标准答案是二", "不得直接包含标准答案"),
        ("请说出最后结果。", "不得完全重复"),
    ],
)
def test_teaching_output_rejects_reveal_and_exact_repeat(
    content: str, expected_error: str
) -> None:
    output = TeachingOutput(
        content=content,
        questions=[{"id": "q1", "question": "最后得到什么结果？"}],
    )

    errors = validate_teaching_output(output=output, context=teaching_context())

    assert any(expected_error in error for error in errors)


def test_teaching_service_records_valid_call_without_state_changes(settings, monkeypatch) -> None:
    database_session = Mock()
    service = AITeachingService(database_session, settings)
    service.repository.record_external_call = Mock(
        return_value=SimpleNamespace(id=1, transport_status="SUCCESS")
    )
    service.repository.record_external_call_validation = Mock()
    content = json.dumps(
        {
            "content": "你已经说明相加过程，请补充最终结果。",
            "questions": [{"id": "q1", "question": "两个一相加得到多少？"}],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        service.client,
        "evaluate",
        lambda request: AIModelResponse("raw", content, 8),
    )
    current_session = Session(status="IN_PROGRESS", support_count_total=0)

    output = service.generate(session=current_session, context=teaching_context())

    assert output.questions[0].id == "q1"
    assert current_session.status == "IN_PROGRESS"
    assert current_session.support_count_total == 0
    service.repository.record_external_call.assert_called_once()
    assert service.repository.record_external_call.call_args.kwargs["call_type"] == "AI_TEACHING"
    assert (
        service.repository.record_external_call.call_args.kwargs["transport_status"] == "SUCCESS"
    )
    request = service.repository.record_external_call.call_args.kwargs["request_snapshot"]
    assert request.purpose == "AI_SUPPORT"
    service.repository.record_external_call_validation.assert_called_once_with(
        record=service.repository.record_external_call.return_value,
        validation_status="VALID",
        validation_errors=[],
    )


def test_teaching_service_does_not_retry_transport_failure(settings, monkeypatch) -> None:
    database_session = Mock()
    service = AITeachingService(database_session, settings)
    service.repository.record_external_call = Mock()
    calls = 0

    def fail_once(request):
        nonlocal calls
        calls += 1
        raise AITransportError(error_type="AI_SERVICE_ERROR", message="服务不可用", duration_ms=5)

    monkeypatch.setattr(service.client, "evaluate", fail_once)

    with pytest.raises(AITeachingError, match="服务不可用"):
        service.generate(session=Session(id=1), context=teaching_context())

    assert calls == 1
    assert (
        service.repository.record_external_call.call_args.kwargs["transport_status"] == "ERROR"
    )
    assert service.repository.record_external_call.call_args.kwargs["request_snapshot"] is not None
