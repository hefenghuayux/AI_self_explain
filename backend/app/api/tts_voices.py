from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.auth import CurrentUser, DatabaseSession
from app.models.tts_voice import TTSSpeechSettings, TTSVoice

router = APIRouter(prefix="/tts-voices", tags=["tts-voices"])


class VoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    display_name: str = Field(serialization_alias="displayName")
    model: str
    subject: str | None
    teacher: str | None
    variant: str | None


class VoiceSettingsResponse(BaseModel):
    voices: list[VoiceResponse]
    selected_voice_id: int | None = Field(serialization_alias="selectedVoiceId")


class VoiceSelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_id: int | None = Field(alias="voiceId", gt=0, strict=True)


def voice_settings_response(
    database_session: DatabaseSession, user_id: int
) -> VoiceSettingsResponse:
    voices = database_session.scalars(select(TTSVoice).order_by(TTSVoice.id)).all()
    preference = database_session.get(TTSSpeechSettings, user_id)
    return VoiceSettingsResponse(
        voices=[VoiceResponse.model_validate(voice) for voice in voices],
        selected_voice_id=preference.voice_id if preference else None,
    )


@router.get("", response_model=VoiceSettingsResponse)
def get_voice_settings(
    database_session: DatabaseSession, user: CurrentUser
) -> VoiceSettingsResponse:
    return voice_settings_response(database_session, user.id)


@router.put("/selection", response_model=VoiceSettingsResponse)
def select_voice(
    selection: VoiceSelectionInput, database_session: DatabaseSession, user: CurrentUser
) -> VoiceSettingsResponse:
    if (
        selection.voice_id is not None
        and database_session.get(TTSVoice, selection.voice_id) is None
    ):
        raise HTTPException(404, "所选音色不存在，请重新选择")
    preference = database_session.get(TTSSpeechSettings, user.id)
    if preference is None:
        preference = TTSSpeechSettings(user_id=user.id, voice_id=selection.voice_id)
        database_session.add(preference)
    else:
        preference.voice_id = selection.voice_id
    database_session.commit()
    return voice_settings_response(database_session, user.id)
