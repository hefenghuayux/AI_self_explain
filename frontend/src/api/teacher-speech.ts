import { getAuthToken } from "../stores/auth"

export type TeacherSpeechRequest = { itemIds: string[] } | { fullSolution: true }

export async function fetchTeacherSpeech(
  sessionId: string,
  request: TeacherSpeechRequest,
  signal: AbortSignal,
): Promise<Blob> {
  const token = getAuthToken()
  if (!token) throw new Error("请先登录后播放老师语音")
  const response = await fetch(`/api/sessions/${sessionId}/teacher-speech`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(request),
    signal,
  })
  if (!response.ok) {
    const body = await response.json() as {
      detail?: string | { message?: string } | Array<{ msg: string }>
    }
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).join("；")
      : typeof body.detail === "string" ? body.detail : body.detail?.message
    throw new Error(detail ?? `语音生成失败：HTTP ${response.status}`)
  }
  if (!response.headers.get("Content-Type")?.toLowerCase().startsWith("audio/")) {
    throw new Error("语音服务返回了非音频内容")
  }
  const audio = await response.blob()
  if (!audio.size) throw new Error("语音服务返回了空音频")
  return audio
}
