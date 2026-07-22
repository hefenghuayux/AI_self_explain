<script setup lang="ts">
import { useRouter } from "vue-router"

import { authUser, isAuthenticated, logout } from "./stores/auth"

const router = useRouter()

async function signOut() {
  await logout()
  await router.push("/login")
}
</script>

<template>
  <el-header v-if="isAuthenticated" class="app-header">
    <strong>AI 自讲 Demo</strong>
    <nav>
      <RouterLink to="/">首页</RouterLink>
      <RouterLink v-if="authUser?.role === 'TEACHER'" to="/questions">题目管理</RouterLink>
      <span>{{ authUser?.fullName }}</span>
      <el-button link @click="signOut">退出登录</el-button>
    </nav>
  </el-header>
  <RouterView />
</template>

<style scoped>
.app-header { display: flex; height: auto; min-height: 60px; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 24px; border-bottom: 1px solid #e5e7eb; background: #fff; flex-wrap: wrap; }
nav { display: flex; align-items: center; justify-content: flex-end; gap: 16px; flex-wrap: wrap; }
nav a { color: #2563eb; text-decoration: none; }
</style>
