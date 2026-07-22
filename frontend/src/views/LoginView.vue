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
    <el-card class="auth-card" shadow="never">
      <template #header><h1>登录 AI 自讲 Demo</h1></template>
      <el-alert v-if="route.query.registered === '1'" title="注册成功，请登录" type="success" :closable="false" show-icon />
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名"><el-input v-model="username" autocomplete="username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="password" type="password" show-password autocomplete="current-password" /></el-form-item>
        <el-checkbox v-model="rememberLogin">记住登录状态</el-checkbox>
        <el-button class="submit-button" type="primary" :loading="submitting" @click="submit">登录</el-button>
      </el-form>
      <RouterLink to="/register">注册学生账号</RouterLink>
    </el-card>
  </main>
</template>

<style scoped>
.auth-page { display: grid; min-height: 100vh; padding: 24px; place-items: center; }
.auth-card { width: min(100%, 420px); }
h1 { margin: 0; font-size: 24px; }
.submit-button { width: 100%; margin: 20px 0 16px; }
</style>
