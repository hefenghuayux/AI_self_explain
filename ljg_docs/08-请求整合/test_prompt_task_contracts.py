import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.support import GuidedAnswerAssessmentOutput, SupportRequestOutput
from app.services.ai_evaluation import _render_prompt
from app.services.ai_support import _render_answer_assessment_prompt, _render_support_prompt


@pytest.fixture
def context():
    question = SimpleNamespace(
        question_content="Explain x + 1 = 3.", standard_answer="x = 2",
        evaluation_mode="FULL_RUBRIC", rubric_points=["subtract one"],
        common_errors=[], alternative_solutions=[], layered_hints=[],
        guided_questions=[], full_solution="Subtract one from both sides.",
    )
    session = SimpleNamespace(round=1, support_count_round=0, covered_points_current_round=[])
    return dict(question=question, session=session, validation_errors=[],
                model="test", prompt_version="test")


@pytest.mark.parametrize("task_type", ["EXPLANATION", "HELP", "GUIDED_ANSWER"])
def test_backend_task_type_reaches_transport(context, task_type):
    if task_type == "EXPLANATION":
        request = _render_prompt(
            **context, attempt=SimpleNamespace(confirmed_text="x = 2"), schema={}
        )
    elif task_type == "HELP":
        request = _render_support_prompt(
            **context, main_draft="x = 2", doubt_text="Why?", force_current_step=False
        )
    else:
        request = _render_answer_assessment_prompt(
            **context, support_event=SimpleNamespace(main_draft="x = 2", guided_questions=[]),
            answers=[],
        )
    assert request.blocks.session_context["taskType"] == task_type
    assert "taskType" not in request.blocks.user_input
    messages = request.transport_payload()["messages"]
    assert len(messages) == 1
    prompt = messages[0]["content"]
    marker = "评价上下文：" if task_type == "EXPLANATION" else "上下文："
    payload, _ = json.JSONDecoder().raw_decode(prompt.split(marker)[-1].lstrip())
    assert payload["taskType"] == task_type
    assert "{{CONTEXT_JSON}}" not in prompt


@pytest.fixture(params=[SupportRequestOutput, GuidedAnswerAssessmentOutput])
def output_case(request):
    payload = {
        "main_reason": "原因未明", "other_reasons": [],
        "judge_reason": "No evidence of a specific difficulty.", "content": "Continue.",
    }
    if request.param is SupportRequestOutput:
        payload.update(action="SIMPLE_DOUBT_ANSWER", coveredPoints=[], questions=[])
    else:
        payload.update(results=[{"questionId": "q1", "result": "CORRECT"}])
    return request.param, payload


def test_reason_contract_accepts_and_preserves_names(output_case):
    model, payload = output_case
    result = model.model_validate_json(json.dumps(payload)).model_dump(by_alias=True)
    for field in ("main_reason", "other_reasons", "judge_reason"):
        assert result[field] == payload[field]


@pytest.mark.parametrize("field", ["main_reason", "other_reasons", "judge_reason"])
def test_reason_fields_are_required(output_case, field):
    model, payload = output_case
    del payload[field]
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("field,value", [
    ("main_reason", "unknown"), ("other_reasons", ["unknown"]), ("judge_reason", " "),
])
def test_invalid_reasons_are_rejected(output_case, field, value):
    model, payload = output_case
    payload[field] = value
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_model_cannot_add_task_selection_to_output(output_case):
    model, payload = output_case
    payload["taskType"] = "EXPLANATION"
    with pytest.raises(ValidationError):
        model.model_validate(payload)
