<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRouter } from "vue-router"

import { authUser, isAuthenticated, logout } from "./stores/auth"
import { fetchTtsVoiceSettings, saveTtsVoiceSelection, type TtsVoice } from "./api/tts-voices"
import { notifyTeacherSpeechVoiceChanged, setTeacherSpeechAutoPlay, teacherSpeechAutoPlay } from "./stores/teacherSpeech"

const router = useRouter()
const menuRef = ref<HTMLDetailsElement>()
const menuOpen = ref(false)
const settingsVisible = ref(false)
const voices = ref<TtsVoice[]>([])
const selectedVoiceId = ref<number | null>(null)
const savedVoiceId = ref<number | null>(null)
const voicesLoading = ref(false)
const voicesLoaded = ref(false)
const voiceSaving = ref(false)
const voiceError = ref("")
const voiceSuccess = ref("")
let settingsGeneration = 0
let voicesController: AbortController | undefined

function closeMenu() {
  if (menuRef.value) menuRef.value.open = false
  menuOpen.value = false
}

function handleOutsideClick(event: PointerEvent) {
  if (event.target instanceof Node && !menuRef.value?.contains(event.target)) closeMenu()
}

function handleEscape(event: KeyboardEvent) {
  if (event.key === "Escape" && menuOpen.value) {
    closeMenu()
    menuRef.value?.querySelector("summary")?.focus()
  }
}

function handleMenuClick(event: MouseEvent) {
  if (event.target instanceof Element && event.target.closest('[role="menuitem"]')) closeMenu()
}

function openSettings() {
  closeMenu()
  settingsVisible.value = true
  void loadVoices()
}

async function loadVoices() {
  voicesController?.abort()
  const controller = new AbortController()
  voicesController = controller
  const generation = ++settingsGeneration
  voicesLoading.value = true
  voicesLoaded.value = false
  voiceError.value = ""
  voiceSuccess.value = ""
  try {
    const settings = await fetchTtsVoiceSettings(controller.signal)
    if (generation !== settingsGeneration) return
    voices.value = settings.voices
    selectedVoiceId.value = settings.selectedVoiceId
    savedVoiceId.value = settings.selectedVoiceId
    voicesLoaded.value = true
  } catch (error) {
    if (generation !== settingsGeneration) return
    voiceError.value = error instanceof Error ? error.message : String(error)
  } finally {
    if (generation === settingsGeneration) voicesLoading.value = false
  }
}

async function saveVoice() {
  if (voiceSaving.value || !voicesLoaded.value) return
  const generation = settingsGeneration
  const userId = authUser.value?.id
  voiceSaving.value = true
  voiceError.value = ""
  voiceSuccess.value = ""
  try {
    const settings = await saveTtsVoiceSelection(selectedVoiceId.value)
    if (userId !== authUser.value?.id) return
    notifyTeacherSpeechVoiceChanged()
    if (generation !== settingsGeneration) return
    voices.value = settings.voices
    selectedVoiceId.value = settings.selectedVoiceId
    savedVoiceId.value = settings.selectedVoiceId
    voiceSuccess.value = "个人音色已保存"
  } catch (error) {
    if (generation !== settingsGeneration) return
    voiceError.value = error instanceof Error ? error.message : String(error)
  } finally {
    if (generation === settingsGeneration) voiceSaving.value = false
  }
}

watch(settingsVisible, (visible) => {
  if (visible) return
  settingsGeneration += 1
  voicesController?.abort()
  voiceSaving.value = false
})
watch(() => authUser.value?.id, () => {
  settingsVisible.value = false
  notifyTeacherSpeechVoiceChanged()
})

function updateAutoPlay(event: Event) {
  setTeacherSpeechAutoPlay((event.target as HTMLInputElement).checked)
}

onMounted(() => {
  document.addEventListener("pointerdown", handleOutsideClick)
  document.addEventListener("keydown", handleEscape)
})
onBeforeUnmount(() => {
  settingsGeneration += 1
  voicesController?.abort()
  document.removeEventListener("pointerdown", handleOutsideClick)
  document.removeEventListener("keydown", handleEscape)
})

async function signOut() {
  await logout()
  await router.push("/login")
}
</script>

<template>
  <header v-if="isAuthenticated" class="app-header">
    <div class="header-inner">
      <RouterLink class="brand" to="/" aria-label="AI 自讲 Demo 题目列表">
        <span class="brand-mark" aria-hidden="true">讲</span>
        <span class="brand-copy">
          <strong>AI 自讲</strong>
          <small>学习闭环 Demo</small>
        </span>
      </RouterLink>
      <nav aria-label="主导航">
        <RouterLink class="nav-link" to="/">题目列表</RouterLink>
      </nav>
      <div class="account-area">
        <span class="user-name">{{ authUser?.fullName }}</span>
        <details
          ref="menuRef"
          class="account-menu"
          @toggle="menuOpen = menuRef?.open ?? false"
        >
          <summary class="menu-trigger" aria-haspopup="menu" :aria-expanded="menuOpen" data-testid="account-menu-trigger">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
            菜单
          </summary>
          <div class="account-menu-panel" role="menu" aria-label="会话与账户菜单" @click="handleMenuClick">
            <!-- 页面级操作由各视图 Teleport 到此容器，与「退出登录」同处下拉菜单。 -->
            <div id="app-header-actions" class="header-actions" />
            <el-button class="logout-button" text role="menuitem" @click="signOut">退出登录</el-button>
          </div>
        </details>
        <button type="button" class="settings-button" aria-label="设置" title="设置" data-testid="settings-button" @click="openSettings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m9.2 3-.5 2.3-1.8 1L4.6 6l-2 3.4 1.8 1.5v2.2l-1.8 1.5 2 3.4 2.3-.3 1.8 1 .5 2.3h3.9l.5-2.3 1.8-1 2.3.3 2-3.4-1.8-1.5v-2.2l1.8-1.5-2-3.4-2.3.3-1.8-1-.5-2.3z" /><circle cx="11.2" cy="12" r="3" /></svg>
        </button>
      </div>
    </div>
  </header>
  <el-dialog v-model="settingsVisible" title="设置" width="min(420px, calc(100vw - 32px))" :close-on-click-modal="!voiceSaving" :close-on-press-escape="!voiceSaving" :show-close="!voiceSaving">
    <label class="auto-play-setting">
      <input :checked="teacherSpeechAutoPlay" type="checkbox" data-testid="teacher-speech-auto-play" @change="updateAutoPlay" />
      自动播放老师回复
    </label>
    <div class="voice-setting">
      <label for="personal-tts-voice">我的老师音色</label>
      <p id="voice-setting-help">仅对当前账号生效。选择并保存后，再播放老师回复。</p>
      <select id="personal-tts-voice" v-model="selectedVoiceId" data-testid="personal-tts-voice" aria-describedby="voice-setting-help" :disabled="voicesLoading || voiceSaving || !voicesLoaded" @change="voiceSuccess = ''">
        <option :value="null">未选择音色（无法生成语音）</option>
        <option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.displayName }}</option>
      </select>
      <p v-if="voicesLoading" role="status">正在加载音色…</p>
      <p v-if="voiceError" class="voice-error" role="alert">{{ voiceError }}</p>
      <p v-if="voiceSuccess" role="status">{{ voiceSuccess }}</p>
      <el-button v-if="!voicesLoaded && !voicesLoading" data-testid="reload-tts-voices" @click="loadVoices">重新加载音色</el-button>
      <el-button v-else type="primary" data-testid="save-tts-voice" :loading="voiceSaving" :disabled="voicesLoading || !voicesLoaded || selectedVoiceId === savedVoiceId" @click="saveVoice">保存个人音色</el-button>
    </div>
  </el-dialog>
  <RouterView :key="$route.fullPath" />
</template>

<style scoped>
.app-header {
  position: sticky;
  z-index: 20;
  top: 0;
  border-bottom: 1px solid var(--color-border);
  background: rgb(255 255 255 / 96%);
  box-shadow: var(--shadow-sm);
}

.header-inner {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto minmax(180px, 1fr);
  align-items: center;
  width: min(100%, var(--content-width));
  min-height: 68px;
  margin: 0 auto;
  padding: var(--space-2) var(--space-6);
  gap: var(--space-6);
}

.brand {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text-primary);
  text-decoration: none;
}

.brand-mark {
  display: grid;
  width: 38px;
  height: 38px;
  border-radius: var(--radius-md);
  color: var(--color-on-brand);
  background: var(--color-brand-700);
  font-size: var(--font-size-lg);
  font-weight: 700;
  place-items: center;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.brand-copy strong {
  font-size: var(--font-size-lg);
}

.brand-copy small {
  margin-top: 2px;
  color: var(--color-text-muted);
  font-size: 12px;
}

nav {
  display: flex;
  align-self: stretch;
  align-items: center;
}

.nav-link {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  padding: 0 var(--space-3);
  border-bottom: 2px solid transparent;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  font-weight: 600;
  text-decoration: none;
}

.nav-link.router-link-exact-active {
  border-color: var(--color-brand-600);
  color: var(--color-brand-700);
}

.account-area {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-3);
}

.user-name {
  overflow: hidden;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: block;
}

.account-menu {
  position: relative;
}

.menu-trigger,
.settings-button {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text-primary);
  background: var(--color-surface);
  cursor: pointer;
  gap: var(--space-2);
}

.menu-trigger {
  padding: 0 var(--space-3);
  list-style: none;
  font-size: var(--font-size-sm);
}

.menu-trigger::-webkit-details-marker {
  display: none;
}

.settings-button {
  width: 44px;
  padding: 0;
}

.menu-trigger svg,
.settings-button svg {
  width: 20px;
  height: 20px;
}

.menu-trigger:hover,
.settings-button:hover {
  background: var(--color-brand-50);
}

.menu-trigger:focus-visible,
.settings-button:focus-visible {
  outline: 2px solid var(--color-brand-600);
  outline-offset: 2px;
}

.account-menu-panel {
  position: absolute;
  z-index: 30;
  top: calc(100% + var(--space-2));
  right: 0;
  width: 184px;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.logout-button {
  width: 100%;
  min-height: 44px;
  justify-content: flex-start;
  margin-left: 0;
}

.auto-play-setting {
  display: flex;
  min-height: 44px;
  align-items: center;
  color: var(--color-text-primary);
  cursor: pointer;
  gap: var(--space-3);
}

.auto-play-setting input {
  width: 18px;
  height: 18px;
  accent-color: var(--color-brand-600);
}

.voice-setting { margin-top: var(--space-4); color: var(--color-text-primary); }
.voice-setting label { font-weight: 600; }
.voice-setting p { margin: var(--space-2) 0; color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.voice-setting select { width: 100%; min-height: 44px; margin-bottom: var(--space-3); padding: var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-sm); color: var(--color-text-primary); background: var(--color-surface); }
.voice-setting select:focus-visible { outline: 2px solid var(--color-brand-600); outline-offset: 2px; }
.voice-setting .voice-error { color: var(--color-error-700); overflow-wrap: anywhere; }

@media (max-width: 640px) {
  .header-inner {
    grid-template-columns: minmax(0, 1fr) auto;
    min-height: 64px;
    padding: var(--space-2) var(--space-4);
    gap: var(--space-2);
  }

  .brand-copy small,
  .user-name,
  nav {
    display: none;
  }

  .account-area {
    flex-wrap: wrap;
    justify-content: flex-end;
  }

}
</style>
