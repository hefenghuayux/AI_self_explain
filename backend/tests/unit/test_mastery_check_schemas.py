import json

import pytest
from pydantic import ValidationError

from app.schemas.mastery_check import (
    MAX_MASTERY_CHECK_QUESTIONS,
    MIN_MASTERY_CHECK_QUESTIONS,
    MasteryCheckAnswerResult,
    MasteryCheckAssessmentOutput,
    MasteryCheckEvidenceRef,
    MasteryCheckQuestion,
    MasteryCheckQuestionsOutput,
    validate_mastery_check_assessment,
    validate_mastery_check_questions,
    validate_question_count,
)


def evidence_ref(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": "EVALUATION",
        "sourceId": "12",
        "quote": "学生写出了配方步骤，但未说明依据。",
    }
    payload.update(overrides)
    return payload


def question_payload(question_id: str = "mc1", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": question_id,
        "question": "你在配方这一步依据的是什么？",
        "evidenceRefs": [evidence_ref()],
    }
    payload.update(overrides)
    return payload


def questions_output(*question_ids: str) -> MasteryCheckQuestionsOutput:
    return MasteryCheckQuestionsOutput(
        questions=[question_payload(question_id) for question_id in question_ids]
    )


def assessment_output(*question_ids: str) -> MasteryCheckAssessmentOutput:
    return MasteryCheckAssessmentOutput(
        results=[
            {"questionId": question_id, "passed": True, "basis": "学生独立说明了依据。"}
            for question_id in question_ids
        ]
    )


@pytest.mark.parametrize(
    "question_count", [MIN_MASTERY_CHECK_QUESTIONS, MAX_MASTERY_CHECK_QUESTIONS]
)
def test_question_count_accepts_one_or_two(question_count: int) -> None:
    assert validate_question_count(question_count) == []


@pytest.mark.parametrize("question_count", [0, MAX_MASTERY_CHECK_QUESTIONS + 1, 5])
def test_question_count_rejects_out_of_range(question_count: int) -> None:
    assert validate_question_count(question_count) == ["核验问题数量必须在 1 到 2 之间"]


def test_questions_output_accepts_two_independent_questions() -> None:
    output = MasteryCheckQuestionsOutput.model_validate_json(
        json.dumps({"questions": [question_payload("mc1"), question_payload("mc2")]})
    )

    assert validate_mastery_check_questions(output) == []
    assert [item.id for item in output.questions] == ["mc1", "mc2"]
    assert output.questions[0].evidence_refs[0].source == "EVALUATION"
    assert output.questions[0].evidence_refs[0].source_id == "12"


def test_questions_output_rejects_duplicate_ids() -> None:
    output = questions_output("mc1", "mc1")

    assert validate_mastery_check_questions(output) == ["核验问题的 id 不能重复"]


def test_questions_output_rejects_empty_question_list() -> None:
    output = MasteryCheckQuestionsOutput(questions=[])

    assert validate_mastery_check_questions(output) == ["核验问题数量必须在 1 到 2 之间"]


def test_questions_output_rejects_more_than_two_questions() -> None:
    output = questions_output("mc1", "mc2", "mc3")

    assert validate_mastery_check_questions(output) == ["核验问题数量必须在 1 到 2 之间"]


def test_question_requires_at_least_one_evidence_ref() -> None:
    with pytest.raises(ValidationError):
        MasteryCheckQuestion.model_validate(question_payload(evidenceRefs=[]))


def test_evidence_ref_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError):
        MasteryCheckEvidenceRef.model_validate(evidence_ref(source="FULL_SOLUTION"))


@pytest.mark.parametrize(
    "field", ["status", "count", "round", "fullSolution", "standardAnswer"]
)
def test_questions_output_rejects_business_fields(field: str) -> None:
    payload = question_payload()
    payload[field] = "不应由 AI 返回"

    with pytest.raises(ValidationError):
        MasteryCheckQuestionsOutput.model_validate(payload)


def test_assessment_output_accepts_results_matching_sent_questions() -> None:
    output = assessment_output("mc1", "mc2")

    assert validate_mastery_check_assessment(output, ["mc1", "mc2"]) == []


def test_assessment_output_rejects_missing_or_extra_question() -> None:
    assert validate_mastery_check_assessment(assessment_output("mc1"), ["mc1", "mc2"]) == [
        "核验回答评价必须与已发送问题一一对应"
    ]
    assert validate_mastery_check_assessment(assessment_output("mc1", "mc2"), ["mc1"]) == [
        "核验回答评价必须与已发送问题一一对应"
    ]


def test_assessment_output_rejects_duplicate_result_for_same_question() -> None:
    output = MasteryCheckAssessmentOutput(
        results=[
            {"questionId": "mc1", "passed": True, "basis": "第一次判断。"},
            {"questionId": "mc1", "passed": False, "basis": "重复判断。"},
        ]
    )

    assert validate_mastery_check_assessment(output, ["mc1"]) == [
        "核验回答评价必须与已发送问题一一对应"
    ]


def test_assessment_result_requires_boolean_passed() -> None:
    with pytest.raises(ValidationError):
        MasteryCheckAnswerResult.model_validate(
            {"questionId": "mc1", "passed": "true", "basis": "字符串不算布尔值。"}
        )


@pytest.mark.parametrize("field", ["status", "round", "fullSolution"])
def test_assessment_output_rejects_business_fields(field: str) -> None:
    payload = {"results": [], field: "不应由 AI 返回"}

    with pytest.raises(ValidationError):
        MasteryCheckAssessmentOutput.model_validate(payload)
