import { getAuthToken } from "../stores/auth"

export interface TtsVoice {
  id: number
  displayName: string
  model: string
  subject: string | null
  teacher: string | null
  variant: string | null
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
  return await response.json() as TtsVoiceSettings
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
