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
        <el-button class="logout-button" plain @click="signOut">退出登录</el-button>
      </div>
    </div>
  </header>
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

  .logout-button {
    padding-right: var(--space-3);
    padding-left: var(--space-3);
  }
}
</style>
