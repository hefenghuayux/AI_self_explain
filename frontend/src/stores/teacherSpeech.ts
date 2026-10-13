import { ref } from "vue"

const preferenceKey = "ai-self-explain:teacher-speech:auto-play"

export const teacherSpeechAutoPlay = ref(localStorage.getItem(preferenceKey) !== "false")
export const teacherSpeechVoiceVersion = ref(0)

export function notifyTeacherSpeechVoiceChanged() {
  teacherSpeechVoiceVersion.value += 1
}

export function setTeacherSpeechAutoPlay(enabled: boolean) {
  localStorage.setItem(preferenceKey, String(enabled))
  teacherSpeechAutoPlay.value = enabled
}
