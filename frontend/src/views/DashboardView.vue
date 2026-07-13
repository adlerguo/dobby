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
    desc: '从模板或空白配置一个业务助手，完成提示词、知识库和工具能力设置。',
    action: '进入模板广场',
    to: '/templates',
  },
  {
    title: '调试知识库',
    desc: '输入真实业务问题，查看命中片段、分数、来源和调优建议。',
    action: '开始命中测试',
    to: '/kbs',
  },
  {
    title: '发布应用',
    desc: '把智能体发布到 Web、API 或机器人渠道，形成上线闭环。',
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
            ['Token', data.token_usage?.total ?? 0, ''],
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
        <p>按“创建、调试、发布、优化”的用户任务组织工作，而不是按后台模块堆入口。</p>
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
            title="有智能体还未发布，建议完成调试后进入发布中心。"
            type="warning"
            :closable="false"
          />
          <el-alert
            v-if="kbs.length"
            title="建议定期使用知识库实验台检查低分召回和引用质量。"
            type="info"
            :closable="false"
          />
          <el-alert title="下一步可配置发布渠道，把可用智能体交付给业务人员。" type="success" :closable="false" />
        </div>
      </article>
      <article class="panel-card">
        <div class="card-header">
          <h2>{{ mode === 'executive' ? '结论摘要' : '最近运行' }}</h2>
        </div>
        <p v-if="mode === 'executive'" class="muted">{{ detail.headline || '暂无摘要' }}</p>
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
          <h2>{{ mode === 'executive' ? '业务构成' : 'Span 类型' }}</h2>
        </div>
        <pre>{{ JSON.stringify(mode === 'executive' ? detail.business_mix || [] : detail.spans_by_type || {}, null, 2) }}</pre>
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
