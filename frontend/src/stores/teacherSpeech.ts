import { ref } from "vue"

const preferenceKey = "ai-self-explain:teacher-speech:auto-play"

export const teacherSpeechAutoPlay = ref(localStorage.getItem(preferenceKey) !== "false")

export function setTeacherSpeechAutoPlay(enabled: boolean) {
  localStorage.setItem(preferenceKey, String(enabled))
  teacherSpeechAutoPlay.value = enabled
}
