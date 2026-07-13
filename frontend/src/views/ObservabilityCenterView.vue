<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { apiFetch } from '../api/client'

const loading = ref(false)
const data = ref<Record<string, any>>({})

async function loadData() {
  loading.value = true
  try {
    data.value = await apiFetch<Record<string, any>>('/dashboard/technical?period_days=7')
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <section>
    <div class="page-header">
      <div>
        <h1>观测中心</h1>
        <p>把运行轨迹、Token 用量、延迟和失败记录组织成可分析的产品页面。</p>
      </div>
      <el-button @click="loadData">刷新</el-button>
    </div>

    <div v-loading="loading" class="grid four">
      <article class="panel-card stat-card">
        <span>调用量</span>
        <strong>{{ data.summary?.run_count || 0 }}</strong>
      </article>
      <article class="panel-card stat-card">
        <span>成功率</span>
        <strong>{{ data.summary?.success_rate || 0 }}<small> %</small></strong>
      </article>
      <article class="panel-card stat-card">
        <span>P95 延迟</span>
        <strong>{{ data.latency?.p95_ms || 0 }}<small> ms</small></strong>
      </article>
      <article class="panel-card stat-card">
        <span>Token</span>
        <strong>{{ data.token_usage?.total || 0 }}</strong>
      </article>
    </div>

    <div class="grid two mt">
      <section class="panel-card">
        <div class="card-header">
          <h2>运行轨迹</h2>
        </div>
        <el-timeline>
          <el-timeline-item v-for="run in (data.recent_runs || [])" :key="run.trace_id || run.id">
            {{ run.agent_name || '未知智能体' }} · {{ run.status }} · {{ run.latency_ms || 0 }}ms
          </el-timeline-item>
        </el-timeline>
      </section>
      <section class="panel-card">
        <div class="card-header">
          <h2>Span 类型</h2>
        </div>
        <pre>{{ JSON.stringify(data.spans_by_type || {}, null, 2) }}</pre>
      </section>
    </div>
  </section>
</template>
