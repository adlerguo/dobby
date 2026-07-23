<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { apiFetch } from '../../api/client'
import type { Agent } from '../../api/types'
import { useAgentsStore } from '../../stores/agents'

type AgentStatus = 'busy' | 'idle' | 'error'

interface AgentMetric {
  agent_name: string
  run_count: number
  success_rate: number
}

interface TechnicalDashboard {
  by_agent?: AgentMetric[]
}

interface FactoryAgent {
  id: string
  name: string
  status: AgentStatus
}

interface StatusMeta {
  key: AgentStatus
  title: string
  empty: string
}

const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

const REFRESH_INTERVAL = 25000
const statusOrder: AgentStatus[] = ['busy', 'idle', 'error']
const statusMeta: StatusMeta[] = [
  { key: 'busy', title: '忙碌区', empty: '暂无忙碌智能体' },
  { key: 'idle', title: '空闲区', empty: '暂无空闲智能体' },
  { key: 'error', title: '异常区', empty: '暂无异常智能体' },
]

const agentsStore = useAgentsStore()
const { agents, loading: agentsLoading } = storeToRefs(agentsStore)
const metrics = ref<AgentMetric[]>([])
const dashboardLoading = ref(false)
const updatedAt = ref<Date | null>(null)

let timer: number | undefined
let disposed = false
let inFlight = false
let warned = false

const loading = computed(() => agentsLoading.value || dashboardLoading.value)
const metricsByName = computed(() => new Map(metrics.value.map((metric) => [metric.agent_name, metric])))
const factoryAgents = computed(() =>
  agents.value
    .map((agent) => ({ id: agent.id, name: agent.name, status: statusFromMetric(metricsByName.value.get(agent.name)) }))
    .sort((a, b) => statusOrder.indexOf(a.status) - statusOrder.indexOf(b.status) || a.name.localeCompare(b.name, 'zh-CN')),
)
const counts = computed(() => ({
  busy: factoryAgents.value.filter((agent) => agent.status === 'busy').length,
  idle: factoryAgents.value.filter((agent) => agent.status === 'idle').length,
  error: factoryAgents.value.filter((agent) => agent.status === 'error').length,
}))
const sections = computed(() =>
  statusMeta.map((meta) => ({
    ...meta,
    agents: factoryAgents.value.filter((agent) => agent.status === meta.key),
  })),
)
const updatedLabel = computed(() => {
  if (!updatedAt.value) return '实时'
  return `${updatedAt.value.getHours().toString().padStart(2, '0')}:${updatedAt.value.getMinutes().toString().padStart(2, '0')} 更新`
})

function dashboardParams() {
  return new URLSearchParams({ period_days: '1' })
}

function statusFromMetric(metric?: AgentMetric): AgentStatus {
  if (!metric || metric.run_count <= 0) return 'idle'
  const successRate = metric.success_rate <= 1 ? metric.success_rate * 100 : metric.success_rate
  return successRate < 100 ? 'error' : 'busy'
}

async function refreshData() {
  if (inFlight || disposed) return
  inFlight = true
  dashboardLoading.value = true
  try {
    const [, dashboard] = await Promise.all([
      agentsStore.fetchAgents(),
      apiFetch<TechnicalDashboard>(`/dashboard/technical?${dashboardParams().toString()}`),
    ])
    if (disposed) return
    metrics.value = dashboard.by_agent || []
    updatedAt.value = new Date()
    warned = false
  } catch (error) {
    if (import.meta.env.DEV) console.error('[FactoryPanel]', error)
    if (!warned) ElMessage.warning('智能体工厂数据暂未更新，已保留上一次画面')
    warned = true
  } finally {
    dashboardLoading.value = false
    inFlight = false
  }
}

function schedule() {
  window.clearInterval(timer)
  timer = window.setInterval(() => {
    if (document.visibilityState === 'visible') void refreshData()
  }, REFRESH_INTERVAL)
}

function onVisibility() {
  if (document.visibilityState === 'visible') {
    void refreshData()
    schedule()
  } else {
    window.clearInterval(timer)
  }
}

function stableHash(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return Math.abs(hash >>> 0)
}

function workerColor(agent: Agent | FactoryAgent) {
  const colors = ['#1D9E75', '#378ADD', '#7F77DD', '#EF9F27', '#D85A30', '#D4537E', '#639922', '#1D9E9E']
  return colors[stableHash(agent.id) % colors.length]
}

function hairColor(agent: Agent | FactoryAgent) {
  const colors = ['#2E2A26', '#3A2E22', '#5A3E2A', '#4A3B2E']
  return colors[stableHash(`${agent.id}:hair`) % colors.length]
}

onMounted(() => {
  disposed = false
  document.addEventListener('visibilitychange', onVisibility)
  void refreshData()
  schedule()
})

onBeforeUnmount(() => {
  disposed = true
  document.removeEventListener('visibilitychange', onVisibility)
  window.clearInterval(timer)
})
</script>

<template>
  <article class="factory-panel" :class="{ 'factory-panel--embedded': props.embedded }" aria-label="智能体工厂运行概览">
    <div v-loading="loading && !updatedAt" class="factory-frame">
      <header class="factory-topbar">
        <div class="factory-topbar__title">
          <span class="status-dot status-dot--busy" />
          <span>运行概览</span>
        </div>
        <div class="factory-topbar__counts" aria-label="智能体状态统计">
          <span><i class="status-dot status-dot--busy" />忙碌 {{ counts.busy }}</span>
          <span><i class="status-dot status-dot--idle" />空闲 {{ counts.idle }}</span>
          <span><i class="status-dot status-dot--error" />异常 {{ counts.error }}</span>
          <span><i class="status-dot status-dot--busy status-dot--live" />{{ updatedLabel }}</span>
        </div>
      </header>

      <section
        v-for="section in sections"
        :key="section.key"
        class="factory-section"
        :class="[`factory-section--${section.key}`, { 'factory-section--empty': section.agents.length === 0 }]"
      >
        <header class="factory-section__header">
          <div>
            <span class="status-dot" :class="`status-dot--${section.key}`" />
            <span>{{ section.title }} · {{ section.agents.length }}</span>
          </div>
          <span v-if="section.key === 'idle'" class="factory-zone-label">休息区</span>
        </header>

        <p v-if="section.agents.length === 0" class="factory-empty">{{ section.empty }}</p>
        <TransitionGroup v-else name="worker-fade" tag="div" class="factory-grid">
          <article
            v-for="agent in section.agents"
            :key="agent.id"
            class="factory-worker"
            :class="`factory-worker--${agent.status}`"
            :style="{ '--worker-color': workerColor(agent), '--hair-color': hairColor(agent) }"
            aria-hidden="true"
          >
            <div class="worker-name-pill">
              <span class="status-dot" :class="`status-dot--${agent.status}`" />
              <span class="worker-name">{{ agent.name }}</span>
            </div>
            <div class="typing-bubble" aria-hidden="true"><span /><span /><span /></div>
            <div class="error-badge" aria-hidden="true">!</div>
            <svg class="worker-svg" viewBox="0 0 132 108" role="img" focusable="false" aria-label="">
              <rect class="desk-top" x="36" y="78" width="60" height="5" />
              <rect class="desk-front" x="36" y="83" width="60" height="12" />
              <rect class="monitor-frame" x="84" y="66" width="20" height="15" rx="2" />
              <rect class="screen-fill" x="86" y="68" width="16" height="11" />
              <rect class="chair-back" x="58" y="96" width="16" height="5" rx="2" />
              <rect class="chair-seat" x="57" y="102" width="18" height="6" rx="3" />
              <g class="coffee-cup">
                <rect x="31" y="75" width="8" height="8" rx="1" />
                <circle cx="39" cy="79" r="3" />
              </g>
              <g class="worker-person">
                <rect class="worker-hand worker-hand--left" x="51" y="55" width="3" height="6" />
                <rect class="worker-hand worker-hand--right" x="78" y="55" width="3" height="6" />
                <rect class="worker-body" x="58" y="45" width="16" height="13" />
                <rect class="worker-head" x="60" y="27" width="12" height="12" />
                <rect class="worker-hair" x="60" y="23" width="12" height="4" />
                <rect class="worker-eye" x="63" y="32" width="2" height="2" />
                <rect class="worker-eye" x="69" y="32" width="2" height="2" />
              </g>
            </svg>
          </article>
        </TransitionGroup>
      </section>

      <footer class="factory-legend">
        <span><i class="status-dot status-dot--busy" />忙碌（最近有运行）</span>
        <span><i class="status-dot status-dot--idle" />空闲（无运行）</span>
        <span><i class="status-dot status-dot--error" />有失败</span>
        <span class="factory-legend__note">每 20–30 秒刷新 · 面板只读</span>
      </footer>
    </div>
  </article>
</template>

<style scoped>
.factory-panel {
  overflow: hidden;
  border: 1px solid var(--color-border-subtle);
  border-radius: 12px;
  background: #f6f2ea;
  box-shadow: var(--shadow-card);
  user-select: none;
}

.factory-frame {
  display: grid;
  gap: 10px;
  width: 100%;
  overflow: visible;
  background: #f6f2ea;
  pointer-events: none;
}

.factory-topbar {
  display: flex;
  min-height: 36px;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 16px;
  border-radius: 12px 12px 0 0;
  background: #2e3138;
  color: #fff;
  font-size: 13px;
  font-weight: 500;
}

.factory-topbar__title,
.factory-topbar__counts,
.factory-section__header,
.factory-legend {
  display: flex;
  align-items: center;
}

.factory-topbar__title,
.factory-section__header > div,
.factory-topbar__counts span,
.factory-legend span {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.factory-topbar__counts {
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 18px;
  color: #e6e9ed;
  font-size: 12px;
  font-weight: 400;
}

.status-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 999px;
}

.status-dot--busy {
  background: #63991f;
}

.status-dot--idle {
  background: #888780;
}

.status-dot--error {
  background: #e24b4a;
}

.status-dot--live {
  width: 6px;
  height: 6px;
}

.factory-section {
  display: grid;
  gap: 8px;
  min-height: 40px;
  padding: 8px;
  border-radius: 8px;
}

.factory-section--busy {
  background: #edf3e6;
}

.factory-section--idle {
  background: #f3eee4;
}

.factory-section--error {
  background: #fbeeee;
}

.factory-section--empty {
  align-content: start;
  gap: 2px;
  min-height: 40px;
  padding-bottom: 6px;
}

.factory-section__header {
  min-height: 26px;
  justify-content: space-between;
  color: #3b6d11;
  font-size: 12px;
  font-weight: 500;
}

.factory-section--idle .factory-section__header {
  color: #6b655a;
}

.factory-section--error .factory-section__header {
  color: #a32d2d;
}

.factory-zone-label {
  display: inline-flex;
  align-items: center;
  min-height: 17px;
  padding: 0 12px;
  border-radius: 999px;
  background: #eae3d5;
  color: #a69e8f;
  font-size: 11px;
  font-weight: 400;
}

.factory-empty {
  margin: -2px 0 0 22px;
  color: #8a8578;
  font-size: 12px;
}

.factory-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 12px;
}

.factory-worker {
  position: relative;
  width: min(132px, 100%);
  height: 150px;
  margin: 0 auto;
  contain: layout paint;
}

.worker-name-pill {
  position: absolute;
  top: 0;
  right: 6px;
  left: 6px;
  z-index: 2;
  display: flex;
  min-height: 15px;
  align-items: flex-start;
  gap: 6px;
  overflow: hidden;
  padding: 2px 9px;
  border: 1px solid #e2dac9;
  border-radius: 8px;
  background: #fff;
  color: #2c2c2a;
  font-size: 11px;
  line-height: 12px;
}

.worker-name-pill .status-dot {
  width: 5px;
  height: 5px;
  margin-top: 4px;
}

.worker-name {
  display: -webkit-box;
  max-height: 24px;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow-wrap: anywhere;
}

.worker-svg {
  position: absolute;
  top: 34px;
  left: 0;
  width: 100%;
  max-width: 132px;
  height: 108px;
  overflow: visible;
}

.desk-top {
  fill: #f3efe7;
}

.desk-front,
.coffee-cup rect {
  fill: #e2dbcc;
}

.monitor-frame {
  fill: #3a3f46;
}

.screen-fill {
  fill: #7e8a93;
}

.chair-back {
  fill: #a6abb4;
}

.chair-seat {
  fill: #b9bec6;
}

.worker-hand,
.worker-head {
  fill: #f2c6a0;
}

.worker-body {
  fill: var(--worker-color);
}

.worker-hair {
  fill: var(--hair-color);
}

.worker-eye {
  fill: #2c2c2a;
}

.typing-bubble {
  position: absolute;
  top: 40px;
  left: 82px;
  z-index: 3;
  display: none;
  width: 16px;
  height: 10px;
  align-items: center;
  justify-content: center;
  gap: 2px;
  border: 1px solid #e2dac9;
  background: #fff;
}

.typing-bubble span {
  width: 2px;
  height: 2px;
  border-radius: 50%;
  animation: typing-dot 1.2s infinite;
  background: #888780;
}

.typing-bubble span:nth-child(2) {
  animation-delay: 0.18s;
}

.typing-bubble span:nth-child(3) {
  animation-delay: 0.36s;
}

.coffee-cup {
  display: none;
}

.coffee-cup circle {
  fill: none;
  stroke: #e2dbcc;
  stroke-width: 1;
}

.error-badge {
  position: absolute;
  top: -7px;
  right: 0;
  z-index: 3;
  display: none;
  width: 14px;
  height: 14px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  animation: error-pulse 1.4s infinite;
  background: #e24b4a;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
}

.factory-worker--busy .screen-fill {
  fill: #8fd0f0;
}

.factory-worker--busy .typing-bubble {
  display: flex;
}

.factory-worker--busy .worker-hand--left {
  animation: typing-hand-left 0.6s infinite;
}

.factory-worker--busy .worker-hand--right {
  animation: typing-hand-right 0.6s infinite;
}

.factory-worker--idle .coffee-cup {
  display: block;
}

.factory-worker--idle .worker-person {
  animation: idle-breathe 1.6s ease-in-out infinite;
}

.factory-worker--error .screen-fill {
  fill: #7a3b3b;
}

.factory-worker--error .error-badge {
  display: flex;
}

.factory-section--error .status-dot--error {
  animation: error-pulse 1.4s infinite;
}

.factory-legend {
  min-height: 40px;
  flex-wrap: wrap;
  gap: 18px;
  padding: 0 16px;
  border-radius: 0 0 12px 12px;
  background: #f1ece2;
  color: #2c2c2a;
  font-size: 12px;
}

.factory-legend__note {
  margin-left: auto;
  color: #8a8578;
}

.worker-fade-enter-active,
.worker-fade-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.worker-fade-enter-from,
.worker-fade-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

.worker-fade-leave-active {
  position: absolute;
}

@keyframes typing-dot {
  0%,
  20% {
    opacity: 1;
  }

  21%,
  100% {
    opacity: 0.25;
  }
}

@keyframes typing-hand-left {
  0%,
  100% {
    transform: translateY(-1px);
  }

  50% {
    transform: translateY(2px);
  }
}

@keyframes typing-hand-right {
  0%,
  100% {
    transform: translateY(2px);
  }

  50% {
    transform: translateY(-1px);
  }
}

@keyframes idle-breathe {
  0%,
  100% {
    transform: translateY(0);
  }

  50% {
    transform: translateY(1px);
  }
}

@keyframes error-pulse {
  0%,
  100% {
    transform: scale(1);
  }

  50% {
    transform: scale(1.14);
  }
}

@media (max-width: 760px) {
  .factory-topbar {
    align-items: flex-start;
    flex-direction: column;
    padding: 10px 12px;
  }

  .factory-topbar__counts {
    justify-content: flex-start;
  }

  .factory-legend__note {
    width: 100%;
    margin-left: 0;
  }
}
</style>
