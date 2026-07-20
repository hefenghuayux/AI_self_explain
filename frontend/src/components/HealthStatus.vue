<script setup lang="ts">
import { onMounted, ref } from "vue"

import { fetchHealth } from "../api/health"

const loading = ref(true)
const errorMessage = ref("")

onMounted(async () => {
  try {
    await fetchHealth()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <el-skeleton v-if="loading" :rows="2" animated />
  <el-alert
    v-else-if="errorMessage"
    title="后端服务连接失败"
    :description="errorMessage"
    type="error"
    :closable="false"
    show-icon
  />
  <el-alert
    v-else
    title="服务运行正常"
    description="FastAPI 与 SQLite 健康检查均已通过。"
    type="success"
    :closable="false"
    show-icon
  />
</template>
