import pytest
from pydantic import ValidationError

from app.schemas.session_event import EVENT_DATA_SCHEMAS, SessionEventResponse


@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        ("session.started", {}),
        ("user.message", {"text": "我的答案", "inputType": "text"}),
        (
            "context.added",
            {"kind": "question", "source": "question:1", "content": "计算 1 + 1"},
        ),
        (
            "model.requested",
            {
                "provider": "test-ai",
                "model": "test-model",
                "messages": [{"role": "user", "content": "评价这段自讲"}],
                "surfaceSeq": 2,
            },
        ),
        ("model.responded", {"output": {}, "validation": "valid"}),
        ("model.failed", {"errorType": "TIMEOUT", "message": "模型请求超时"}),
        (
            "state.changed",
            {"from": "EVALUATING", "to": "WAIT_STUDENT_ACTION", "reason": "completed"},
        ),
    ],
)
def test_all_event_payloads_accept_the_documented_shape(
    event_type: str, data: dict[str, object]
) -> None:
    validated = EVENT_DATA_SCHEMAS[event_type].model_validate(data)

    assert validated.model_dump(by_alias=True, exclude_none=True) == data


def test_event_payload_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EVENT_DATA_SCHEMAS["session.started"].model_validate({"unexpected": True})


def test_event_response_uses_camel_case_and_omits_empty_correlation_fields() -> None:
    response = SessionEventResponse.model_validate(
        {
            "session_id": 1,
            "seq": 0,
            "event_id": "evt_1",
            "event_type": "session.started",
            "occurred_at": "2026-08-20T10:20:30Z",
            "data": {},
        }
    )

    assert response.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "sessionId": 1,
        "seq": 0,
        "eventId": "evt_1",
        "eventType": "session.started",
        "occurredAt": "2026-08-20T10:20:30Z",
        "data": {},
    }
