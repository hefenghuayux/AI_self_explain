<script setup lang="ts">
import { ref } from "vue"
import { useRoute, useRouter } from "vue-router"

import { login } from "../stores/auth"

const router = useRouter()
const route = useRoute()
const username = ref("")
const password = ref("")
const rememberLogin = ref(false)
const submitting = ref(false)
const errorMessage = ref("")

async function submit() {
  if (!username.value.trim() || !password.value) {
    errorMessage.value = "请输入用户名和密码"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    await login(username.value, password.value, rememberLogin.value)
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/"
    await router.push(redirect.startsWith("/") ? redirect : "/")
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-panel" aria-labelledby="login-title">
      <div class="auth-heading">
        <span class="brand-mark" aria-hidden="true">讲</span>
        <div>
          <h1 id="login-title">登录 AI 自讲</h1>
          <p>继续你的自讲学习进度</p>
        </div>
      </div>
      <el-alert v-if="route.query.registered === '1'" title="注册成功，请登录" type="success" :closable="false" show-icon />
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名"><el-input v-model="username" autocomplete="username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="password" type="password" show-password autocomplete="current-password" /></el-form-item>
        <el-checkbox v-model="rememberLogin">记住登录状态</el-checkbox>
        <el-button class="submit-button" type="primary" :loading="submitting" @click="submit">登录</el-button>
      </el-form>
      <p class="auth-switch">还没有账号？<RouterLink to="/register">注册学生账号</RouterLink></p>
    </section>
  </main>
</template>

<style scoped>
.auth-page { display: grid; min-height: 100vh; padding: var(--space-6); background: var(--color-page); place-items: center; }
.auth-panel { width: min(100%, 440px); min-width: 0; padding: var(--space-8); border: 1px solid var(--color-border); border-radius: var(--radius-lg); background: var(--color-surface); box-shadow: var(--shadow-md); }
.auth-panel .el-form, .auth-panel .el-input { width: 100%; min-width: 0; }
.auth-heading { display: flex; align-items: center; gap: var(--space-4); margin-bottom: var(--space-6); }
.brand-mark { display: grid; width: 48px; height: 48px; flex: 0 0 auto; border-radius: var(--radius-md); color: var(--color-on-brand); background: var(--color-brand-700); font-size: 22px; font-weight: 700; place-items: center; }
h1 { margin: 0; font-size: var(--font-size-xl); line-height: 1.35; }
.auth-heading p, .auth-switch { margin: var(--space-1) 0 0; color: var(--color-text-muted); font-size: var(--font-size-sm); }
.el-alert { margin-bottom: var(--space-4); }
.submit-button { width: 100%; margin: var(--space-6) 0 var(--space-4); }
.auth-switch { text-align: center; }
@media (max-width: 640px) { .auth-page { padding: var(--space-4); background: var(--color-page); } .auth-panel { padding: var(--space-6) var(--space-4); box-shadow: none; } }
</style>
