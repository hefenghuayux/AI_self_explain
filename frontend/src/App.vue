<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRouter } from "vue-router"

import { authUser, isAuthenticated, logout } from "./stores/auth"
import { fetchTtsVoiceSettings, saveTtsVoiceSelection, type TtsVoice } from "./api/tts-voices"
import { notifyTeacherSpeechVoiceChanged, setTeacherSpeechAutoPlay, teacherSpeechAutoPlay } from "./stores/teacherSpeech"

const router = useRouter()
const menuRef = ref<HTMLDetailsElement>()
const menuOpen = ref(false)
const settingsVisible = ref(false)
const voicePickerVisible = ref(false)
const voices = ref<TtsVoice[]>([])
const selectedVoiceId = ref<number | null>(null)
const savedVoiceId = ref<number | null>(null)
const voicesLoading = ref(false)
const voicesLoaded = ref(false)
const voiceSaving = ref(false)
const voiceError = ref("")
const voiceSuccess = ref("")
const educationStageFilter = ref("")
const subjectFilter = ref("")
const genderFilter = ref("")
const nameFilter = ref("")
let settingsGeneration = 0
let voicesController: AbortController | undefined

const educationStageOptions = computed(() => [...new Set(voices.value.map((voice) => voice.educationStage).filter((value): value is string => Boolean(value)))])
const subjectOptions = computed(() => [...new Set(voices.value.map((voice) => voice.subject).filter((value): value is string => Boolean(value)))])
const genderOptions = computed(() => [...new Set(voices.value.map((voice) => voice.gender).filter((value): value is string => Boolean(value)))])
const filteredVoices = computed(() => {
  const nameQuery = nameFilter.value.trim().toLocaleLowerCase()
  return voices.value.filter((voice) => (
    (!educationStageFilter.value || voice.educationStage === educationStageFilter.value)
    && (!subjectFilter.value || voice.subject === subjectFilter.value)
    && (!genderFilter.value || voice.gender === genderFilter.value)
    && (!nameQuery || voice.name.toLocaleLowerCase().includes(nameQuery))
  ))
})
const selectedVoice = computed(() => voices.value.find((voice) => voice.id === selectedVoiceId.value))

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

function openVoicePicker() {
  voicePickerVisible.value = true
  if (!voicesLoaded.value && !voicesLoading.value) void loadVoices()
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
    if (selectedVoiceId.value === null && settings.voices[0]) {
      selectedVoiceId.value = settings.voices[0].id
      void saveVoice()
    }
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
  voicePickerVisible.value = false
  settingsGeneration += 1
  voicesController?.abort()
  voiceSaving.value = false
})
watch(() => authUser.value?.id, () => {
  settingsVisible.value = false
  voicePickerVisible.value = false
  notifyTeacherSpeechVoiceChanged()
})

function updateAutoPlay(event: Event) {
  setTeacherSpeechAutoPlay((event.target as HTMLInputElement).checked)
}

function selectVoice(voiceId: number) {
  selectedVoiceId.value = voiceId
  voiceSuccess.value = ""
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
            <RouterLink class="menu-item mobile-question-list" role="menuitem" to="/">题目列表</RouterLink>
            <!-- 页面级操作由各视图 Teleport 到此容器，与「退出登录」同处下拉菜单。 -->
            <div id="app-header-actions" class="header-actions" />
            <RouterLink class="menu-item user-guide-link" role="menuitem" to="/guide" data-testid="user-guide-link">使用指南</RouterLink>
            <button type="button" class="menu-item logout-button" role="menuitem" @click="signOut">退出登录</button>
          </div>
        </details>
        <button type="button" class="settings-button" aria-label="设置" title="设置" data-testid="settings-button" @click="openSettings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m9.2 3-.5 2.3-1.8 1L4.6 6l-2 3.4 1.8 1.5v2.2l-1.8 1.5 2 3.4 2.3-.3 1.8 1 .5 2.3h3.9l.5-2.3 1.8-1 2.3.3 2-3.4-1.8-1.5v-2.2l1.8-1.5-2-3.4-2.3.3-1.8-1-.5-2.3z" /><circle cx="11.2" cy="12" r="3" /></svg>
        </button>
      </div>
    </div>
  </header>
  <el-dialog v-model="settingsVisible" class="settings-dialog" title="设置" width="min(420px, calc(100vw - 32px))" :close-on-click-modal="!voiceSaving" :close-on-press-escape="!voiceSaving" :show-close="!voiceSaving">
    <label class="auto-play-setting">
      <input :checked="teacherSpeechAutoPlay" type="checkbox" data-testid="teacher-speech-auto-play" @change="updateAutoPlay" />
      自动播放老师回复
    </label>
    <div class="voice-setting">
      <div class="voice-setting-heading">
        <div>
          <strong>我的老师音色</strong>
          <p id="voice-setting-help">仅对当前账号生效。选择并保存后，再播放老师回复。</p>
        </div>
        <el-button data-testid="open-tts-voice-picker" :disabled="voicesLoading || voiceSaving" @click="openVoicePicker">设置音色</el-button>
      </div>
      <p v-if="selectedVoice">当前选择：{{ selectedVoice.name }}<span v-if="selectedVoice.remark"> · {{ selectedVoice.remark }}</span></p>
      <p v-else>尚未选择音色</p>
      <p v-if="voicesLoading" role="status">正在加载音色…</p>
      <p v-if="voiceError" class="voice-error" role="alert">{{ voiceError }}</p>
      <p v-if="voiceSuccess" role="status">{{ voiceSuccess }}</p>
      <el-button v-if="!voicesLoaded && !voicesLoading" data-testid="reload-tts-voices" @click="loadVoices">重新加载音色</el-button>
    </div>
  </el-dialog>
  <el-dialog v-model="voicePickerVisible" class="voice-picker-dialog" title="选择老师音色" width="min(680px, calc(100vw - 32px))" :close-on-click-modal="!voiceSaving" :close-on-press-escape="!voiceSaving" :show-close="!voiceSaving">
    <div class="voice-filters" aria-label="音色筛选">
      <select v-model="educationStageFilter" data-testid="tts-voice-stage-filter" aria-label="按学段筛选">
        <option value="">全部学段</option>
        <option v-for="stage in educationStageOptions" :key="stage" :value="stage">{{ stage }}</option>
      </select>
      <select v-model="subjectFilter" data-testid="tts-voice-subject-filter" aria-label="按学科筛选">
        <option value="">全部学科</option>
        <option v-for="subject in subjectOptions" :key="subject" :value="subject">{{ subject }}</option>
      </select>
      <select v-model="genderFilter" data-testid="tts-voice-gender-filter" aria-label="按性别筛选">
        <option value="">全部性别</option>
        <option v-for="gender in genderOptions" :key="gender" :value="gender">{{ gender }}</option>
      </select>
      <input v-model="nameFilter" data-testid="tts-voice-name-filter" aria-label="按名字筛选" placeholder="输入名字筛选" />
    </div>
    <div v-if="voicesLoading" class="voice-picker-status" role="status">正在加载音色…</div>
    <div v-else-if="filteredVoices.length" class="voice-options" role="listbox" aria-label="可选音色">
      <button
        v-for="voice in filteredVoices"
        :key="voice.id"
        type="button"
        class="voice-option"
        :class="{ 'voice-option-selected': voice.id === selectedVoiceId }"
        :aria-selected="voice.id === selectedVoiceId"
        role="option"
        :disabled="voiceSaving"
        @click="selectVoice(voice.id)"
      >
        <span class="voice-option-name">{{ voice.name }}</span>
        <span v-if="voice.remark" class="voice-option-remark">{{ voice.remark }}</span>
      </button>
    </div>
    <p v-else class="voice-picker-status">没有符合条件的音色</p>
    <p v-if="voiceError" class="voice-error" role="alert">{{ voiceError }}</p>
    <p v-if="voiceSuccess" role="status">{{ voiceSuccess }}</p>
    <template #footer>
      <el-button @click="voicePickerVisible = false">取消</el-button>
      <el-button v-if="!voicesLoaded && !voicesLoading" data-testid="reload-tts-voices" @click="loadVoices">重新加载音色</el-button>
      <el-button v-else type="primary" data-testid="save-tts-voice" :loading="voiceSaving" :disabled="voicesLoading || !voicesLoaded || selectedVoiceId === savedVoiceId" @click="saveVoice">保存个人音色</el-button>
    </template>
  </el-dialog>
  <RouterView :key="$route.fullPath" />
</template>

<style scoped>
.app-header {
  position: sticky;
  z-index: 20;
  top: 0;
  border-bottom: 1px solid rgb(255 255 255 / 16%);
  color: var(--color-shell-text);
  background: var(--background-shell);
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
  color: var(--color-shell-text);
  text-decoration: none;
}

.brand-mark {
  display: grid;
  width: 38px;
  height: 38px;
  border-radius: var(--radius-control);
  color: var(--color-on-brand);
  background: var(--gradient-action);
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
  color: var(--color-shell-text);
  font-size: var(--font-size-sm);
  font-weight: 600;
  text-decoration: none;
}

.nav-link.router-link-exact-active {
  border-color: var(--color-accent-cyan);
  background: rgb(255 255 255 / 10%);
}

.nav-link:hover {
  background: rgb(255 255 255 / 16%);
}

.brand:focus-visible,
.nav-link:focus-visible {
  outline: 2px solid var(--color-accent-cyan);
  outline-offset: 2px;
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
  color: var(--color-shell-text);
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
  border: 1px solid rgb(255 255 255 / 32%);
  border-radius: var(--radius-control);
  color: var(--color-shell-text);
  background: rgb(255 255 255 / 8%);
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
.settings-button:hover,
.account-menu[open] .menu-trigger {
  border-color: var(--color-accent-cyan);
  background: rgb(255 255 255 / 16%);
}

.menu-trigger:focus-visible,
.settings-button:focus-visible {
  outline: 2px solid var(--color-accent-cyan);
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
  border-radius: var(--radius-card);
  color: var(--color-text-primary);
  background: var(--color-surface);
  box-shadow: var(--shadow-md);
}

/* 菜单项统一为同一行样式；页面级操作由视图 Teleport 注入，需用 :deep 命中其作用域节点。 */
.account-menu-panel :deep(.menu-item) {
  display: flex;
  width: 100%;
  min-height: 44px;
  align-items: center;
  padding: 0 var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  color: var(--color-text-primary);
  background: transparent;
  font-size: var(--font-size-sm);
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}

.account-menu-panel :deep(.menu-item:hover:not(:disabled)),
.account-menu-panel :deep(.menu-item.router-link-exact-active) {
  color: var(--color-brand-700);
  background: var(--color-brand-50);
}

.account-menu-panel :deep(.menu-item:focus-visible) {
  outline: 2px solid var(--color-brand-600);
  outline-offset: -2px;
}

.account-menu-panel :deep(.menu-item:disabled) {
  opacity: .5;
  cursor: default;
}

.account-menu-panel .mobile-question-list { display: none; }

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
.voice-setting-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.voice-setting p { margin: var(--space-2) 0; color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.voice-setting .voice-error { color: var(--color-error-700); overflow-wrap: anywhere; }
.voice-filters { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-2); margin-bottom: var(--space-4); }
.voice-filters select, .voice-filters input { width: 100%; min-height: 40px; padding: var(--space-2); border: 1px solid var(--color-border); border-radius: var(--radius-sm); color: var(--color-text-primary); background: var(--color-surface); }
.voice-filters input { grid-column: span 3; }
.voice-filters select:focus-visible, .voice-filters input:focus-visible { outline: 2px solid var(--color-brand-600); outline-offset: 2px; }
.voice-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); max-height: min(50vh, 420px); overflow: auto; gap: var(--space-2); padding: 2px; }
.voice-option { display: flex; min-height: 64px; flex-direction: column; align-items: flex-start; justify-content: center; padding: var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-sm); color: var(--color-text-primary); background: var(--color-surface); cursor: pointer; text-align: left; }
.voice-option:hover, .voice-option-selected { border-color: var(--color-brand-600); background: var(--color-brand-50); }
.voice-option:focus-visible { outline: 2px solid var(--color-brand-600); outline-offset: 2px; }
.voice-option-name { font-weight: 600; }
.voice-option-remark { margin-top: 4px; color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.voice-picker-status { margin: var(--space-4) 0; color: var(--color-text-secondary); text-align: center; }
:global(.settings-dialog), :global(.voice-picker-dialog) { max-height: calc(100dvh - 32px); margin: 16px auto; }
:global(.settings-dialog .el-dialog__body), :global(.voice-picker-dialog .el-dialog__body) { min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
:global(.settings-dialog .el-dialog__footer), :global(.voice-picker-dialog .el-dialog__footer) { border-top: 1px solid var(--color-border); }
:global(.voice-picker-dialog .el-dialog__body) { max-height: calc(100dvh - 180px); }

@media (max-width: 640px) {
  .header-inner {
    grid-template-columns: minmax(0, 1fr) auto;
    min-height: 64px;
    padding: var(--space-2) var(--space-4);
    gap: var(--space-2);
  }

  .user-name,
  nav {
    display: none;
  }

  .account-menu-panel .mobile-question-list { display: flex; }

  .account-area {
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .voice-filters { grid-template-columns: 1fr 1fr; }
  .voice-filters input { grid-column: span 2; }
  .voice-options { grid-template-columns: 1fr; }
  :global(.settings-dialog), :global(.voice-picker-dialog) { width: calc(100vw - 16px) !important; margin: 8px auto; }
  :global(.voice-picker-dialog .el-dialog__body) { max-height: calc(100dvh - 140px); }

}
</style>
