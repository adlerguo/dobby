<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { apiFetch } from '../api/client'
import type { Workspace } from '../api/types'

const workspaces = ref<Workspace[]>([])
const loading = ref(false)
const creating = ref(false)
const name = ref('默认工作空间')

async function loadWorkspaces() {
  loading.value = true
  try {
    workspaces.value = await apiFetch<Workspace[]>('/workspaces')
  } finally {
    loading.value = false
  }
}

async function createWorkspace() {
  creating.value = true
  try {
    await apiFetch<Workspace>('/workspaces', {
      method: 'POST',
      body: { name: name.value, layout: { view: 'workbench' } },
    })
    await loadWorkspaces()
  } finally {
    creating.value = false
  }
}

onMounted(loadWorkspaces)
</script>

<template>
  <section>
    <div class="page-header">
      <div>
        <h1>工作空间</h1>
        <p>按项目组织智能体、知识库、模型和工具能力，便于分组管理。</p>
      </div>
      <el-button @click="loadWorkspaces">刷新</el-button>
    </div>

    <div class="grid two">
      <section class="panel-card">
        <el-table v-loading="loading" :data="workspaces" border>
          <el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column label="资源数" width="120">
            <template #default="{ row }">{{ row.resources?.length || 0 }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" min-width="180" />
        </el-table>
      </section>
      <section class="panel-card">
        <div class="card-header">
          <h2>新建空间</h2>
        </div>
        <el-input v-model="name" />
        <el-button class="mt" type="primary" :loading="creating" @click="createWorkspace">创建</el-button>
      </section>
    </div>
  </section>
</template>
