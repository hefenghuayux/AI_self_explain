import { getAuthToken } from "../stores/auth"

export interface TtsVoice {
  id: number
  educationStage: string | null
  subject: string | null
  name: string
  remark: string | null
  gender: string | null
  voiceType: string
}

export interface TtsVoiceSettings {
  voices: TtsVoice[]
  selectedVoiceId: number | null
}

async function requestVoiceSettings(path: string, options?: RequestInit): Promise<TtsVoiceSettings> {
  const token = getAuthToken()
  if (!token) throw new Error("请先登录后设置音色")
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    const body = await response.json() as { detail?: string | { message?: string } | Array<{ msg: string }> }
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).join("；")
      : typeof body.detail === "string" ? body.detail : body.detail?.message
    throw new Error(detail ?? `音色设置失败：HTTP ${response.status}`)
  }
  const settings = await response.json() as TtsVoiceSettings
  if (!Array.isArray(settings.voices) || settings.voices.some((voice) => (
    !voice || typeof voice.name !== "string" || !voice.name.trim()
    || !("educationStage" in voice) || !("remark" in voice)
    || !("gender" in voice) || !("voiceType" in voice)
  ))) {
    throw new Error("音色数据格式与当前页面不匹配，请更新后端服务并完成数据库迁移后重试")
  }
  return settings
}

export function fetchTtsVoiceSettings(signal: AbortSignal): Promise<TtsVoiceSettings> {
  return requestVoiceSettings("/api/tts-voices", { signal })
}

export function saveTtsVoiceSelection(voiceId: number | null): Promise<TtsVoiceSettings> {
  return requestVoiceSettings("/api/tts-voices/selection", {
    method: "PUT",
    body: JSON.stringify({ voiceId }),
  })
}
