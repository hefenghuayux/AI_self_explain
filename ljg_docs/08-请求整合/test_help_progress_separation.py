from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.api.sessions import apply_support_request_output
from app.rules.teaching_decision import decide_teaching
from app.schemas.merged import MergedModelOutput, validate_merged_output
from app.schemas.support import SupportRequestOutput
from app.services.ai_evaluation import _render_prompt
from app.services.ai_support import _render_support_prompt, _validate_support_request


def reasons():
    return dict(main_reason="原因未明", other_reasons=[], judge_reason="Evidence is limited.")


def support(action="GUIDED_QUESTIONS"):
    return SupportRequestOutput(
        **reasons(), action=action, content="Consider the current step.",
        questions=[{"id": "q1", "question": "Why?"}] if action == "GUIDED_QUESTIONS" else [],
    )


@pytest.mark.parametrize("action,method", [
    ("GUIDED_QUESTIONS", "record_guided_questions"),
    ("SIMPLE_DOUBT_ANSWER", "record_direct_help"),
    ("REFUSE_FULL_SOLUTION", "record_full_solution_refusal"),
])
def test_help_only_records_selected_response(action, method):
    repository = Mock(spec=[method])
    session = SimpleNamespace(no_progress_count=8, no_progress_help_request_count=9)
    result = apply_support_request_output(
        repository=repository, session=session, main_draft="", doubt_text="Why?",
        output=support(action), settings=SimpleNamespace(),
    )
    assert result is getattr(repository, method).return_value
    assert len(repository.mock_calls) == 1
    assert session.no_progress_count == 8
    assert session.no_progress_help_request_count == 9


def test_help_has_no_coverage_and_rejects_removed_action():
    output = support()
    assert _validate_support_request(output) == []
    payload = output.model_dump(by_alias=True)
    assert "coveredPoints" not in payload
    with pytest.raises(ValidationError):
        SupportRequestOutput.model_validate({**payload, "coveredPoints": []})
    with pytest.raises(ValidationError):
        SupportRequestOutput.model_validate({**payload, "action": "CURRENT_STEP_ANSWER"})


def merged(progress, points, action):
    return MergedModelOutput(
        **reasons(), correctness="CORRECT", completeness="INCOMPLETE",
        covered_points=points, error_evidence=[], need_human_reason=None,
        has_progress=progress, teaching_action=action, content="Continue.",
        questions=[{"id": "q1", "question": "Why?"}] if action == "ASK_FOCUSED_QUESTION" else [],
    )


@pytest.mark.parametrize("progress,points,action,count", [
    (True, [], "ASK_FOCUSED_QUESTION", 0),
    (False, [1], "GIVE_HINT", 5),
])
def test_progress_is_independent_of_coverage(progress, points, action, count):
    session = SimpleNamespace(
        covered_points_current_round=[], covered_points_all=[], no_progress_count=4,
        round=1, support_count_round=0,
    )
    result = decide_teaching(
        merged_output=merged(progress, points, action), session=session,
        settings=SimpleNamespace(first_round_support_limit=6, second_round_support_limit=3),
    )
    assert result.allowed_action == action
    assert result.coverage.no_progress_count == count


def test_no_progress_cannot_return_question_action():
    errors = validate_merged_output(merged(False, [], "ASK_FOCUSED_QUESTION"), ["step"], "text")
    assert "无进展时 teachingAction 必须为 GIVE_HINT" in errors


def test_progress_is_required_boolean():
    payload = merged(True, [], "ASK_FOCUSED_QUESTION").model_dump(by_alias=True)
    del payload["hasProgress"]
    with pytest.raises(ValidationError):
        MergedModelOutput.model_validate(payload)
    with pytest.raises(ValidationError):
        MergedModelOutput.model_validate({**payload, "hasProgress": "false"})


def test_actual_prompts_separate_help_and_explanation_progress():
    question = SimpleNamespace(
        question_content="Solve.", standard_answer="2", evaluation_mode="FULL_RUBRIC",
        rubric_points=["step"], common_errors=[], alternative_solutions=[],
        layered_hints=[], guided_questions=[], full_solution="Solution.",
    )
    session = SimpleNamespace(round=1, support_count_round=0, covered_points_current_round=[])
    common = dict(question=question, session=session, validation_errors=[],
                  model="test", prompt_version="test")
    help_request = _render_support_prompt(**common, main_draft="", doubt_text="Why?")
    help_text = help_request.transport.messages[0].content
    for removed in ("coveredPoints", "forceCurrentStepAnswer", "CURRENT_STEP_ANSWER"):
        assert removed not in help_text
    history = {"previousExplanations": ["Previous reasoning"],
               "previousTeaching": [{"content": "Previous hint"}]}
    explanation = _render_prompt(
        **common, attempt=SimpleNamespace(confirmed_text="Alternative reasoning"),
        schema={}, progress_context=history,
    )
    text = explanation.transport.messages[0].content
    assert "Previous reasoning" in text
    assert "Previous hint" in text
    assert "Alternative reasoning" in text
    assert explanation.blocks.session_context["progressContext"] == history
