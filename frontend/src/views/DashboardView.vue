<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { apiFetch } from '../api/client'
import type { Agent, KnowledgeBase, Workspace } from '../api/types'

type DashboardMode = 'executive' | 'technical'

const mode = ref<DashboardMode>('executive')
const loading = ref(false)
const metrics = ref<Array<[string, string | number, string]>>([])
const detail = ref<Record<string, any>>({})
const agents = ref<Agent[]>([])
const kbs = ref<KnowledgeBase[]>([])
const workspaces = ref<Workspace[]>([])

const actionCards = [
  {
    title: '创建智能体',
    desc: '从模板或空白开始，配置面向某类业务任务的 AI 助手。',
    action: '进入模板广场',
    to: '/templates',
  },
  {
    title: '命中测试',
    desc: '使用真实问题进行命中测试，检查企业专属资料库是否能召回正确片段。',
    action: '开始命中测试',
    to: '/kbs',
  },
  {
    title: '发布应用',
    desc: '将已验证的智能体发布给业务人员使用，并持续管理访问方式。',
    action: '进入发布中心',
    to: '/publish',
  },
]

async function loadDashboard(nextMode: DashboardMode = mode.value) {
  mode.value = nextMode
  loading.value = true
  try {
    const endpoint = nextMode === 'technical' ? '/dashboard/technical?period_days=7' : '/dashboard/executive?period_days=7'
    const data = await apiFetch<Record<string, any>>(endpoint)
    detail.value = data
    metrics.value =
      nextMode === 'technical'
        ? [
            ['运行次数', data.summary?.run_count ?? 0, '次'],
            ['成功率', data.summary?.success_rate ?? 0, '%'],
            ['P95 延迟', data.latency?.p95_ms ?? 0, 'ms'],
            ['资源用量', data.token_usage?.total ?? 0, ''],
          ]
        : (data.scorecards || []).map((item: any) => [item.label, item.value, item.unit || ''])
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadDashboard()
  Promise.allSettled([
    apiFetch<Agent[]>('/agents').then((rows) => (agents.value = rows)),
    apiFetch<KnowledgeBase[]>('/kbs').then((rows) => (kbs.value = rows)),
    apiFetch<Workspace[]>('/workspaces').then((rows) => (workspaces.value = rows)),
  ])
})
</script>

<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1>首页工作台</h1>
        <p>统览平台运行概况，并快速进入常用操作。</p>
      </div>
      <el-segmented
        v-model="mode"
        :options="[
          { label: '决策总览', value: 'executive' },
          { label: '运行洞察', value: 'technical' },
        ]"
        @change="loadDashboard(mode)"
      />
    </div>

    <div class="grid three">
      <RouterLink v-for="card in actionCards" :key="card.title" class="task-card" :to="card.to">
        <div class="card-body">
          <h2>{{ card.title }}</h2>
          <p>{{ card.desc }}</p>
        </div>
        <span class="action card-actions">{{ card.action }}</span>
      </RouterLink>
    </div>

    <div v-loading="loading" class="grid four metric-grid">
      <article class="panel-card stat-card">
        <span>智能体</span>
        <strong>{{ agents.length }}<small> 个</small></strong>
      </article>
      <article class="panel-card stat-card">
        <span>知识库</span>
        <strong>{{ kbs.length }}<small> 个</small></strong>
      </article>
      <article class="panel-card stat-card">
        <span>工作空间</span>
        <strong>{{ workspaces.length }}<small> 个</small></strong>
      </article>
      <article v-for="[label, value, unit] in metrics" :key="label" class="panel-card stat-card">
        <span>{{ label }}</span>
        <strong>{{ value }}<small v-if="unit"> {{ unit }}</small></strong>
      </article>
    </div>

    <div class="grid two">
      <article class="panel-card">
        <div class="card-header">
          <h2>推荐动作</h2>
        </div>
        <div class="stack">
          <el-alert
            v-if="agents.some((agent) => agent.status !== 'active')"
            title="有智能体尚未发布。完成问答验证后，可进入发布中心提供给业务人员使用。"
            type="warning"
            :closable="false"
          />
          <el-alert
            v-if="kbs.length"
            title="建议定期使用命中测试检查知识库召回效果与引用质量。"
            type="info"
            :closable="false"
          />
          <el-alert title="下一步可发布已验证的智能体，让业务人员直接使用。" type="success" :closable="false" />
        </div>
      </article>
      <article class="panel-card">
        <div class="card-header">
          <h2>{{ mode === 'executive' ? '结论摘要' : '最近运行' }}</h2>
        </div>
        <p v-if="mode === 'executive'" class="muted">{{ detail.headline || '当前暂无摘要。可先创建智能体并完成一次问答验证。' }}</p>
        <el-timeline v-else>
          <el-timeline-item v-for="run in (detail.recent_runs || [])" :key="run.trace_id || run.id">
            {{ run.agent_name || '未知智能体' }} · {{ run.status }} · {{ run.latency_ms || 0 }}ms
          </el-timeline-item>
        </el-timeline>
      </article>
    </div>

    <div class="grid two">
      <article class="panel-card">
        <div class="card-header">
          <h2>{{ mode === 'executive' ? '业务构成' : '运行环节' }}</h2>
        </div>
        <el-collapse>
          <el-collapse-item title="原始数据（开发者）" name="raw-data">
            <pre>{{ JSON.stringify(mode === 'executive' ? detail.business_mix || [] : detail.spans_by_type || {}, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </article>
      <article class="panel-card">
        <div class="card-header">
          <h2>最近智能体</h2>
        </div>
        <el-table :data="agents.slice(0, 5)" border>
          <el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column prop="type" label="类型" width="120" />
          <el-table-column prop="status" label="状态" width="120" />
        </el-table>
      </article>
    </div>
  </section>
</template>
