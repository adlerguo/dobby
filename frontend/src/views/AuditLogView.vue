<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { apiFetch } from '../api/client'
import type { AuditLog } from '../api/types'

const rows = ref<AuditLog[]>([])
const action = ref('')
const loading = ref(false)

async function loadAudit() {
  loading.value = true
  try {
    const path = action.value ? `/audit-logs?limit=30&action=${encodeURIComponent(action.value)}` : '/audit-logs?limit=30'
    rows.value = await apiFetch<AuditLog[]>(path)
  } finally {
    loading.value = false
  }
}

onMounted(loadAudit)
</script>

<template>
  <section>
    <div class="page-header">
      <div>
        <h1>审计</h1>
        <p>查看企业内关键操作记录，便于追踪配置变更和使用情况。</p>
      </div>
      <div style="display: flex; gap: 8px">
        <el-input v-model="action" placeholder="按操作类型过滤" clearable />
        <el-button @click="loadAudit">查询</el-button>
      </div>
    </div>
    <section class="panel-card">
      <el-table v-loading="loading" :data="rows" border>
        <el-table-column prop="created_at" label="时间" min-width="180" />
        <el-table-column prop="action" label="动作" width="180" />
        <el-table-column prop="resource_type" label="资源" width="160" />
        <el-table-column label="详情" min-width="260">
          <template #default="{ row }">
            <el-collapse>
              <el-collapse-item title="原始数据（开发者）" name="raw-data">
                <pre>{{ JSON.stringify(row.detail || {}, null, 2) }}</pre>
              </el-collapse-item>
            </el-collapse>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </section>
</template>
