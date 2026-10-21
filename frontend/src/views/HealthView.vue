<script setup lang="ts">
import HealthStatus from "../components/HealthStatus.vue"
import { authUser } from "../stores/auth"
</script>

<template>
  <main class="health-page">
    <section class="health-card">
      <h1>AI 自讲 Demo</h1>
      <p class="intro">服务状态检查</p>
      <HealthStatus />
      <RouterLink v-if="authUser?.role === 'TEACHER'" class="question-link" to="/questions">
        <el-button type="primary">进入题目管理</el-button>
      </RouterLink>
    </section>
  </main>
</template>

<style scoped>
.health-page {
  display: grid;
  min-height: 100vh;
  padding: var(--space-8) var(--space-6);
  background: var(--background-shell);
  place-items: center;
}

.health-card {
  width: min(100%, 640px);
  padding: var(--space-8);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-page);
  background: var(--color-surface);
  box-shadow: var(--shadow-md);
}

h1 {
  margin: 0;
  font-size: var(--font-size-2xl);
}

.intro {
  margin: var(--space-2) 0 var(--space-6);
  color: var(--color-text-muted);
}

.question-link {
  display: inline-block;
  margin-top: var(--space-6);
}
@media (max-width: 640px) { .health-page { min-height: 100dvh; padding: var(--space-4) var(--space-3); } .health-card { padding: var(--space-6) var(--space-4); } .question-link, .question-link .el-button { width: 100%; } }
</style>
