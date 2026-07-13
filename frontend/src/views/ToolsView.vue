<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { apiFetch } from '../api/client'
import type { Tool } from '../api/types'

const tools = ref<Tool[]>([])
const loading = ref(false)

async function loadTools() {
  loading.value = true
  try {
    tools.value = await apiFetch<Tool[]>('/tools')
  } finally {
    loading.value = false
  }
}

onMounted(loadTools)
</script>

<template>
  <section>
    <div class="page-header">
      <div>
        <h1>工具</h1>
        <p>查看当前租户可用工具。</p>
      </div>
      <el-button @click="loadTools">刷新</el-button>
    </div>
    <section class="panel-card">
      <el-table v-loading="loading" :data="tools" border>
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="type" label="类型" width="140" />
        <el-table-column prop="status" label="状态" width="120" />
      </el-table>
    </section>
  </section>
</template>
