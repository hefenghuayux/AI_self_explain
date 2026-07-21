import pytest
from pydantic import ValidationError

from app.schemas.question import QuestionInput


def question_payload() -> dict[str, object]:
    return {
        "questionContent": "  计算 1 + 1。  ",
        "standardAnswer": "  2  ",
        "rubricPoints": ["正确计算加法"],
        "commonErrors": ["把结果写成 3"],
        "alternativeSolutions": ["使用实物计数"],
        "layeredHints": ["先数一数两个数"],
        "guidedQuestions": ["两个 1 合起来表示什么？"],
        "fullSolution": "1 加 1 等于 2。",
    }


def test_question_input_accepts_complete_material_and_strips_whitespace() -> None:
    question = QuestionInput.model_validate(question_payload())

    assert question.question_content == "计算 1 + 1。"
    assert question.standard_answer == "2"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("questionContent", " "),
        ("standardAnswer", ""),
        ("commonErrors", []),
        ("alternativeSolutions", [""]),
        ("layeredHints", [" "]),
        ("guidedQuestions", []),
        ("guidedQuestions", [" "]),
        ("fullSolution", " "),
    ],
)
def test_question_input_rejects_missing_or_blank_required_material(
    field: str, value: object
) -> None:
    payload = question_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        QuestionInput.model_validate(payload)


def test_question_input_rejects_blank_rubric_point() -> None:
    payload = question_payload()
    payload["rubricPoints"] = ["正确计算加法", " "]

    with pytest.raises(ValidationError):
        QuestionInput.model_validate(payload)


def test_question_input_rejects_duplicate_rubric_points() -> None:
    payload = question_payload()
    payload["rubricPoints"] = ["正确计算加法", "正确计算加法"]

    with pytest.raises(ValidationError, match="评分点不能重复"):
        QuestionInput.model_validate(payload)


def test_question_input_rejects_duplicate_guided_questions() -> None:
    payload = question_payload()
    payload["guidedQuestions"] = ["先求什么？", "先求什么？"]

    with pytest.raises(ValidationError, match="提示子问题不能重复"):
        QuestionInput.model_validate(payload)
