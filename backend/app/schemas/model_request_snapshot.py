from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelRequestMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user"]
    content: str


class ModelTransportSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[ModelRequestMessage]
    response_format: dict[str, object]
    reasoning_effort: str | None = None
    extra_body: dict[str, object] = Field(default_factory=dict)


class ModelRequestBlocks(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    system_instructions: str = Field(alias="systemInstructions")
    question_context: dict[str, object] = Field(alias="questionContext")
    session_context: dict[str, object] = Field(alias="sessionContext")
    memory_context: dict[str, object] | None = Field(default=None, alias="memoryContext")
    user_input: dict[str, object] = Field(alias="userInput")
    retry_context: dict[str, object] = Field(alias="retryContext")


class ModelRequestPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    contains_student_content: bool = Field(alias="containsStudentContent")
    contains_answer_material: bool = Field(alias="containsAnswerMaterial")
    contains_memory: bool = Field(alias="containsMemory")


class ModelRequestSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["1.0"] = Field(default="1.0", alias="schemaVersion")
    purpose: Literal[
        "AI_EVALUATION",
        "AI_TEACHING",
        "AI_SUPPORT",
        "GUIDED_ANSWER_ASSESSMENT",
    ]
    prompt_version: str = Field(alias="promptVersion")
    blocks: ModelRequestBlocks
    transport: ModelTransportSnapshot
    privacy: ModelRequestPrivacy

    def database_value(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)

    def transport_payload(self) -> dict[str, object]:
        payload = self.transport.model_dump(
            mode="json", exclude_none=True, exclude={"extra_body"}
        )
        if self.transport.extra_body:
            payload.update(self.transport.extra_body)
        return payload
