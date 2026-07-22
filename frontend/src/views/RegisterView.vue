<script setup lang="ts">
import { ref } from "vue"
import { useRouter } from "vue-router"

import { register } from "../stores/auth"

const router = useRouter()
const username = ref("")
const password = ref("")
const fullName = ref("")
const submitting = ref(false)
const errorMessage = ref("")

async function submit() {
  if (!username.value.trim() || !password.value || !fullName.value.trim()) {
    errorMessage.value = "请填写用户名、密码和姓名"
    return
  }
  if (password.value.length < 6) {
    errorMessage.value = "密码至少需要 6 位"
    return
  }
  submitting.value = true
  errorMessage.value = ""
  try {
    await register(username.value, password.value, fullName.value)
    await router.push({ name: "login", query: { registered: "1" } })
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
      <template #header><h1>注册学生账号</h1></template>
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名"><el-input v-model="username" autocomplete="username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="password" type="password" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="fullName" autocomplete="name" /></el-form-item>
        <el-button class="submit-button" type="primary" :loading="submitting" @click="submit">注册</el-button>
      </el-form>
      <RouterLink to="/login">返回登录</RouterLink>
    </el-card>
  </main>
</template>

<style scoped>
.auth-page { display: grid; min-height: 100vh; padding: 24px; place-items: center; }
.auth-card { width: min(100%, 420px); }
h1 { margin: 0; font-size: 24px; }
.submit-button { width: 100%; margin: 8px 0 16px; }
</style>
