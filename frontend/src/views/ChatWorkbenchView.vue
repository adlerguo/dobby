<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { API_BASE, apiFetch } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'
import type { Agent, Citation, Workspace } from '../api/types'

interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
}

interface TraceCard {
  title: string
  status: 'running' | 'success' | 'warning' | 'error'
  detail: string
}

const agents = ref<Agent[]>([])
const workspaces = ref<Workspace[]>([])
const agentId = ref('')
const workspaceId = ref('')
const input = ref('合同审批要注意什么？')
const messages = ref<ChatMessage[]>([])
const citations = ref<Citation[]>([])
const runMeta = ref<Record<string, unknown> | null>(null)
const traceCards = ref<TraceCard[]>([])
const citationDrawer = ref(false)
const selectedCitation = ref<Citation | null>(null)
const streaming = ref(false)

async function loadOptions() {
  const [agentRows, workspaceRows] = await Promise.all([apiFetch<Agent[]>('/agents'), apiFetch<Workspace[]>('/workspaces')])
  agents.value = agentRows.filter((agent) => agent.status === 'active')
  workspaces.value = workspaceRows
  agentId.value = agentId.value || agents.value[0]?.id || ''
}

function parseSseEvent(raw: string) {
  const event = { event: 'message', data: {} as any }
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event.event = line.slice(6).trim()
    if (line.startsWith('data:')) {
      try {
        event.data = JSON.parse(line.slice(5).trim())
      } catch {
        event.data = {}
      }
    }
  }
  return event
}

async function sendMessage() {
  const query = input.value.trim()
  if (!agentId.value || !query) return

  messages.value.push({ role: 'user', text: query })
  const assistant: ChatMessage = { role: 'assistant', text: '' }
  messages.value.push(assistant)
  input.value = ''
  citations.value = []
  runMeta.value = null
  traceCards.value = [
    { title: '思考', status: 'running', detail: '正在判断问题是否需要检索知识库或调用工具。' },
  ]
  streaming.value = true

  try {
    const response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token') || ''}`,
      },
      body: JSON.stringify({
        agent_id: agentId.value,
        workspace_id: workspaceId.value || null,
        query,
        max_tool_rounds: 1,
      }),
    })
    if (!response.ok || !response.body) throw new Error(await response.text())

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        const event = parseSseEvent(part)
        if (event.event === 'delta') assistant.text += event.data.text || ''
        if (event.event === 'citation') {
          citations.value.push(event.data)
          traceCards.value.push({
            title: '知识库检索',
            status: 'success',
            detail: `命中引用：${event.data.doc_name || event.data.doc_id || '未知来源'}，分数 ${event.data.score ?? '-'}`,
          })
        }
        if (event.event === 'done') {
          runMeta.value = event.data
          traceCards.value = traceCards.value.map((card) => (card.status === 'running' ? { ...card, status: 'success' } : card))
          traceCards.value.push({
            title: '生成回答',
            status: 'success',
            detail: `trace_id ${event.data.trace_id || '无'} · Token ${event.data.usage?.total_tokens || 0}`,
          })
        }
        if (event.event === 'error') {
          assistant.text += `\n${event.data.detail || '请求失败'}`
          traceCards.value.push({ title: '运行错误', status: 'error', detail: event.data.detail || '请求失败' })
        }
      }
    }
  } finally {
    streaming.value = false
  }
}

function openCitation(citation: Citation) {
  selectedCitation.value = citation
  citationDrawer.value = true
}

function copyCitationSnippet() {
  if (selectedCitation.value?.snippet) {
    window.navigator.clipboard?.writeText(selectedCitation.value.snippet)
  }
}

onMounted(loadOptions)
</script>

<template>
  <section class="chat-workbench-page">
    <PageHeader title="调试对话" description="选择智能体和工作空间，验证回答、引用和运行信息。">
      <template #actions>
        <el-button @click="loadOptions">刷新选项</el-button>
      </template>
    </PageHeader>

    <div class="grid two">
      <section class="panel-card">
        <SectionHeader title="智能体对话" description="发送问题，观察模型回答和引用返回。" />
        <div class="grid two">
          <el-select v-model="agentId" placeholder="请选择智能体">
            <el-option v-for="agent in agents" :key="agent.id" :label="agent.name" :value="agent.id" />
          </el-select>
          <el-select v-model="workspaceId" clearable placeholder="不使用工作空间">
            <el-option v-for="workspace in workspaces" :key="workspace.id" :label="workspace.name" :value="workspace.id" />
          </el-select>
        </div>
        <div class="chat-box mt">
          <div class="messages">
            <EmptyState v-if="messages.length === 0" title="还没有对话" description="选择智能体后即可发送问题，验证回答质量和引用。" />
            <div v-for="(message, index) in messages" :key="index" class="message" :class="{ user: message.role === 'user' }">
              <strong>{{ message.role === 'user' ? '我' : '智能体' }}</strong>
              <div>{{ message.text || (message.role === 'assistant' && streaming ? '生成中...' : '') }}</div>
            </div>
          </div>
          <div class="chat-input">
            <el-input v-model="input" type="textarea" :rows="2" placeholder="输入问题" @keyup.enter.exact.prevent="sendMessage" />
            <el-button type="primary" :loading="streaming" @click="sendMessage">发送</el-button>
          </div>
        </div>
      </section>

      <section class="panel-card">
        <SectionHeader title="运行轨迹与引用证据" description="查看检索、生成、引用和 trace 信息。" />
        <div class="stack">
          <div class="trace-card" v-for="card in traceCards" :key="card.title + card.detail">
            <strong><StatusTag :status="card.status" :label="card.title" /></strong>
            <p class="muted">{{ card.detail }}</p>
          </div>
          <el-alert :title="`引用 ${citations.length} 条，点击引用可查看证据链。`" type="info" :closable="false" />
          <article v-for="(citation, index) in citations" :key="citation.chunk_id || index" class="result-card">
            <div class="result-meta">
              <strong>{{ citation.doc_name || `引用 ${index + 1}` }}</strong>
              <StatusTag v-if="citation.score != null" status="success" :label="Number(citation.score).toFixed(3)" />
              <span v-if="citation.chunk_id" class="mono-id">{{ citation.chunk_id }}</span>
            </div>
            <p>{{ citation.snippet }}</p>
            <el-button size="small" @click="openCitation(citation)">查看证据链 [{{ index + 1 }}]</el-button>
          </article>
          <article v-if="runMeta" class="result-card">
            <pre>{{ JSON.stringify(runMeta, null, 2) }}</pre>
          </article>
        </div>
      </section>
    </div>

    <el-drawer v-model="citationDrawer" title="引用详情" size="420px">
      <div v-if="selectedCitation" class="stack">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="来源文档">{{ selectedCitation.doc_name || '未知文档' }}</el-descriptions-item>
          <el-descriptions-item label="相似度">{{ selectedCitation.score ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="片段 ID">{{ selectedCitation.chunk_id || '-' }}</el-descriptions-item>
        </el-descriptions>
        <section class="result-card">
          <strong>命中片段</strong>
          <p>{{ selectedCitation.snippet }}</p>
        </section>
        <div class="form-actions">
          <el-button>打开文档详情</el-button>
          <el-button type="primary" @click="copyCitationSnippet">复制原文</el-button>
        </div>
      </div>
    </el-drawer>
  </section>
</template>
