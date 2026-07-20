<script setup lang="ts">
import HealthStatus from "../components/HealthStatus.vue"
</script>

<template>
  <main class="health-page">
    <el-card class="health-card" shadow="never">
      <template #header>
        <div>
          <p class="eyebrow">AI SELF-EXPLANATION</p>
          <h1>AI 自讲 Demo</h1>
        </div>
      </template>
      <p class="intro">阶段 01：项目骨架与配置</p>
      <HealthStatus />
      <RouterLink class="question-link" to="/questions">
        <el-button type="primary">进入题目管理</el-button>
      </RouterLink>
    </el-card>
  </main>
</template>

<style scoped>
.health-page {
  display: grid;
  min-height: 100vh;
  padding: 24px;
  place-items: center;
}

.health-card {
  width: min(100%, 640px);
  border: 1px solid #e5e7eb;
}

.eyebrow {
  margin: 0 0 8px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

h1 {
  margin: 0;
  font-size: clamp(28px, 5vw, 40px);
}

.intro {
  margin: 0 0 24px;
  color: #6b7280;
}

.question-link {
  display: inline-block;
  margin-top: 20px;
}
</style>
