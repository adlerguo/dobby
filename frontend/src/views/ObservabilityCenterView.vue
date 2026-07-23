<script setup lang="ts">
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, type GridComponentOption, type TooltipComponentOption } from 'echarts/components'
import { type BarSeriesOption, type LineSeriesOption } from 'echarts/charts'
import { type ComposeOption, type ECharts, init, use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import { apiFetch } from '../api/client'
import type { Agent } from '../api/types'
import EmptyState from '../components/common/EmptyState.vue'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'

use([LineChart, BarChart, GridComponent, TooltipComponent, CanvasRenderer])

type ChartOption = ComposeOption<LineSeriesOption | BarSeriesOption | GridComponentOption | TooltipComponentOption>

interface DailyMetric {
  date: string
  run_count: number
  success_rate: number
  p95_ms: number
  token_total: number
}

interface AgentMetric {
  agent_id?: string
  agent_name: string
  run_count: number
  success_rate: number
}

interface RecentRun {
  trace_id: string
  agent_name?: string
  status?: string
  latency_ms?: number | null
  tokens?: number | null
  created_at?: string
}

interface TechnicalDashboard {
  summary?: Record<string, any>
  spans_by_type?: Record<string, number>
  spans_by_status?: Record<string, number>
  latency?: Record<string, number | null>
  token_usage?: Record<string, number>
  daily?: DailyMetric[]
  by_agent?: AgentMetric[]
  recent_runs?: RecentRun[]
}

const loading = ref(false)
const agentsLoading = ref(false)
const data = ref<TechnicalDashboard>({})
const agents = ref<Agent[]>([])
const dateRange = ref<string[]>([])
const selectedAgentId = ref('')
const statusFilter = ref('')
const spanTypeFilter = ref('')
const knownSpanTypes = ref<string[]>([])

const chartRefs = {
  run: ref<HTMLDivElement | null>(null),
  success: ref<HTMLDivElement | null>(null),
  latency: ref<HTMLDivElement | null>(null),
  tokens: ref<HTMLDivElement | null>(null),
  agents: ref<HTMLDivElement | null>(null),
  spans: ref<HTMLDivElement | null>(null),
}
const charts: Partial<Record<keyof typeof chartRefs, ECharts>> = {}

const daily = computed(() => data.value.daily || [])
const byAgent = computed(() => data.value.by_agent || [])
const recentRuns = computed(() => data.value.recent_runs || [])
const spansByType = computed(() => data.value.spans_by_type || {})
const hasRuns = computed(() => Number(data.value.summary?.run_count || 0) > 0)
const spanTypeOptions = computed(() => Array.from(new Set([...knownSpanTypes.value, ...Object.keys(spansByType.value)])).sort())

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '成功', value: 'ok' },
  { label: '失败', value: 'failed' },
]

async function loadAgents() {
  agentsLoading.value = true
  try {
    agents.value = await apiFetch<Agent[]>('/agents')
  } finally {
    agentsLoading.value = false
  }
}

async function loadData() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    params.set('period_days', '7')
    if (dateRange.value.length === 2) {
      params.set('start', dateRange.value[0])
      params.set('end', dateRange.value[1])
    }
    if (selectedAgentId.value) params.set('agent_id', selectedAgentId.value)
    if (statusFilter.value) params.set('status', statusFilter.value)
    if (spanTypeFilter.value) params.set('span_type', spanTypeFilter.value)
    data.value = await apiFetch<TechnicalDashboard>(`/dashboard/technical?${params.toString()}`)
    knownSpanTypes.value = Array.from(new Set([...knownSpanTypes.value, ...Object.keys(data.value.spans_by_type || {})])).sort()
  } finally {
    loading.value = false
  }
}

function refreshData() {
  void loadData()
}

function statusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    ok: '成功',
    failed: '失败',
    running: '运行中',
  }
  return labels[String(status || '')] || String(status || '未知')
}

function spanTypeLabel(value: string) {
  const labels: Record<string, string> = {
    agent: '智能体运行',
    agent_run: '智能体运行',
    model: '模型调用',
    model_call: '模型调用',
    tool: '工具调用',
    tool_call: '工具调用',
    retrieval: '知识库检索',
    kb_retrieval: '知识库检索',
  }
  return labels[value] || value
}

function formatDateTime(value?: string) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function baseLineOption(title: string, labels: string[], values: Array<number | null>, unit = ''): ChartOption {
  return {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => `${value}${unit}`,
    },
    grid: { left: 42, right: 16, top: 24, bottom: 34 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#6b7280' },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#6b7280' },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    },
    series: [
      {
        name: title,
        type: 'line',
        smooth: true,
        data: values,
        symbolSize: 6,
        lineStyle: { color: '#2563eb', width: 2 },
        itemStyle: { color: '#2563eb' },
        areaStyle: { color: 'rgba(37, 99, 235, 0.08)' },
      },
    ],
  }
}

function barOption(labels: string[], values: number[], name: string): ChartOption {
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 88, right: 20, top: 18, bottom: 28 },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#6b7280' },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    },
    yAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#4b5563' },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    series: [
      {
        name,
        type: 'bar',
        data: values,
        barWidth: 14,
        itemStyle: { color: '#2563eb', borderRadius: [0, 4, 4, 0] },
      },
    ],
  }
}

function verticalBarOption(labels: string[], values: number[], name: string): ChartOption {
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 48, right: 16, top: 24, bottom: 34 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#6b7280' },
      axisLine: { lineStyle: { color: '#e5e7eb' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#6b7280' },
      splitLine: { lineStyle: { color: '#eef2f7' } },
    },
    series: [
      {
        name,
        type: 'bar',
        data: values,
        barWidth: 16,
        itemStyle: { color: '#16a34a', borderRadius: [4, 4, 0, 0] },
      },
    ],
  }
}

async function syncCharts() {
  await nextTick()
  const labels = daily.value.map((item) => item.date.slice(5))
  setChart('run', baseLineOption('调用量', labels, daily.value.map((item) => item.run_count), ' 次'))
  setChart('success', baseLineOption('成功率', labels, daily.value.map((item) => item.success_rate), '%'))
  setChart('latency', baseLineOption('P95 延迟', labels, daily.value.map((item) => item.p95_ms), ' ms'))
  setChart('tokens', verticalBarOption(labels, daily.value.map((item) => item.token_total), 'Token'))
  setChart(
    'agents',
    barOption(
      [...byAgent.value].reverse().map((item) => item.agent_name),
      [...byAgent.value].reverse().map((item) => item.run_count),
      '运行次数',
    ),
  )
  const spanEntries = Object.entries(spansByType.value).sort((a, b) => b[1] - a[1])
  setChart(
    'spans',
    barOption(
      spanEntries.reverse().map(([name]) => spanTypeLabel(name)),
      spanEntries.map(([, value]) => value),
      '运行环节数量',
    ),
  )
}

function setChart(key: keyof typeof chartRefs, option: ChartOption) {
  const el = chartRefs[key].value
  if (!el) return
  if (charts[key] && charts[key]?.getDom() !== el) {
    charts[key]?.dispose()
    delete charts[key]
  }
  if (!charts[key]) charts[key] = init(el)
  charts[key]?.setOption(option, true)
}

function resizeCharts() {
  Object.values(charts).forEach((chart) => chart?.resize())
}

function disposeCharts() {
  Object.values(charts).forEach((chart) => chart?.dispose())
  Object.keys(charts).forEach((key) => delete charts[key as keyof typeof chartRefs])
}

onMounted(async () => {
  await Promise.all([loadAgents(), loadData()])
  window.addEventListener('resize', resizeCharts)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeCharts)
  disposeCharts()
})

watch(data, syncCharts, { deep: true })
</script>

<template>
  <section class="observability-page">
    <PageHeader title="观测中心" description="按时间、智能体与运行状态查看调用趋势、成功率、响应时间和资源用量。">
      <template #actions>
        <el-button :loading="loading" @click="loadData">刷新</el-button>
      </template>
    </PageHeader>

    <section class="panel-card filter-panel">
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        clearable
        @change="refreshData"
      />
      <el-select v-model="selectedAgentId" :loading="agentsLoading" clearable placeholder="全部智能体" @change="refreshData">
        <el-option label="全部智能体" value="" />
        <el-option v-for="agent in agents" :key="agent.id" :label="agent.name" :value="agent.id" />
      </el-select>
      <el-select v-model="statusFilter" placeholder="全部状态" @change="refreshData">
        <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="spanTypeFilter" clearable placeholder="全部运行环节类型" @change="refreshData">
        <el-option label="全部运行环节类型" value="" />
        <el-option v-for="item in spanTypeOptions" :key="item" :label="spanTypeLabel(item)" :value="item" />
      </el-select>
    </section>

    <el-skeleton v-if="loading && !data.summary" :rows="8" animated />

    <template v-else>
      <div class="grid four">
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
          <span>资源用量</span>
          <strong>{{ data.token_usage?.total || 0 }}</strong>
        </article>
      </div>

      <EmptyState
        v-if="!hasRuns"
        class="panel-card"
        title="还没有运行数据"
        description="请先完成一次智能体对话或调整筛选条件，页面将展示调用趋势、成功率、延迟和资源用量。"
      />

      <div class="chart-grid">
        <section class="panel-card chart-card">
          <SectionHeader title="调用趋势" description="每日智能体运行次数。" />
          <div :ref="(el) => { chartRefs.run.value = el as HTMLDivElement | null }" class="chart-box" />
        </section>
        <section class="panel-card chart-card">
          <SectionHeader title="成功率趋势" :description="`当前成功率 ${data.summary?.success_rate || 0}%`" />
          <div :ref="(el) => { chartRefs.success.value = el as HTMLDivElement | null }" class="chart-box" />
        </section>
        <section class="panel-card chart-card">
          <SectionHeader title="P95 延迟趋势" description="每日较慢请求的响应耗时。" />
          <div :ref="(el) => { chartRefs.latency.value = el as HTMLDivElement | null }" class="chart-box" />
        </section>
        <section class="panel-card chart-card">
          <SectionHeader title="Token 趋势" description="每日智能体运行消耗的 Token 总量。" />
          <div :ref="(el) => { chartRefs.tokens.value = el as HTMLDivElement | null }" class="chart-box" />
        </section>
        <section class="panel-card chart-card">
          <SectionHeader title="按智能体 Top" description="按运行次数展示智能体使用情况。" />
          <EmptyState
            v-if="byAgent.length === 0"
            title="暂无智能体运行排行"
            description="当前条件下暂无智能体运行排行。请调整时间段或选择全部智能体查看。"
          />
          <div v-else :ref="(el) => { chartRefs.agents.value = el as HTMLDivElement | null }" class="chart-box" />
        </section>
        <section class="panel-card chart-card">
          <SectionHeader title="运行环节" description="按运行环节类型展示当前筛选条件下的运行分布。" />
          <EmptyState
            v-if="Object.keys(spansByType).length === 0"
            title="暂无运行环节"
            description="当前条件下暂无运行环节数据。请调整时间段、状态或运行环节类型后查看。"
          />
          <div v-else :ref="(el) => { chartRefs.spans.value = el as HTMLDivElement | null }" class="chart-box" />
        </section>
      </div>

      <section class="panel-card">
        <SectionHeader title="运行轨迹" description="最近的智能体运行记录，便于快速定位异常或高延迟请求。" />
        <EmptyState
          v-if="recentRuns.length === 0"
          title="暂无运行轨迹"
          description="当前条件下暂无运行记录。请调整筛选条件，或先完成一次智能体对话。"
        />
        <el-timeline v-else>
          <el-timeline-item
            v-for="run in recentRuns"
            :key="run.trace_id"
            :timestamp="formatDateTime(run.created_at)"
            :type="run.status === 'failed' ? 'danger' : 'success'"
          >
            <div class="run-item">
              <strong>{{ run.agent_name || '未知智能体' }}</strong>
              <span>{{ statusLabel(run.status) }} · {{ run.latency_ms || 0 }}ms · {{ run.tokens || 0 }} tokens</span>
              <StatusTag :status="run.status || 'unknown'" :label="statusLabel(run.status)" />
            </div>
          </el-timeline-item>
        </el-timeline>
      </section>
    </template>
  </section>
</template>

<style scoped>
.observability-page {
  display: grid;
  gap: var(--space-6);
}

.filter-panel {
  display: grid;
  grid-template-columns: minmax(280px, 1.4fr) repeat(3, minmax(150px, 1fr));
  gap: var(--space-3);
  align-items: center;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.chart-card {
  min-height: 360px;
}

.chart-box {
  width: 100%;
  height: 260px;
}

.run-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.run-item strong {
  color: var(--color-text-primary);
}

.run-item span {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-help);
}

@media (max-width: 1100px) {
  .filter-panel,
  .chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
