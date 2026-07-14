<script setup lang="ts">
import { onMounted, ref } from 'vue'
import MarkdownIt from 'markdown-it'

import { API_BASE, apiFetch } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'
import type { Agent, Citation, KnowledgeChunk, Workspace } from '../api/types'

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
const citationContextChunks = ref<KnowledgeChunk[]>([])
const citationContextLoading = ref(false)
const streaming = ref(false)
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const defaultTextRenderer = md.renderer.rules.text || ((tokens, idx) => md.utils.escapeHtml(tokens[idx].content))
md.renderer.rules.text = (tokens, idx, options, env, self) => {
  const escaped = defaultTextRenderer(tokens, idx, options, env, self)
  return escaped.replace(/\[(\d{1,3})\]/g, '<span class="citation-inline">[$1]</span>')
}

md.renderer.rules.fence = (tokens, idx, options) => {
  const token = tokens[idx]
  const info = token.info ? md.utils.escapeHtml(token.info.trim().split(/\s+/)[0]) : 'text'
  const content = md.utils.escapeHtml(token.content)
  return `<div class="markdown-codeblock"><div class="markdown-codebar"><span>${info}</span><button type="button" class="markdown-copy">复制</button></div><pre><code class="language-${info}">${content}</code></pre></div>`
}

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

function friendlyChatError(detail: string) {
  if (detail === 'no_active_model_channel') return '请先在模型中心配置模型 API 并测试连通'
  if (detail.startsWith('provider_http_')) return `模型渠道调用失败：${detail}，请检查 API Key、额度或供应商地址`
  if (detail === 'maas_call_failed') return '模型网关调用失败，请检查模型渠道配置'
  return detail
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
          const exists = citations.value.some((citation) => citation.chunk_id && citation.chunk_id === event.data.chunk_id)
          if (!exists) {
            citations.value.push(event.data)
            traceCards.value.push({
              title: '知识库检索',
              status: 'success',
              detail: `命中引用：${citationTitle(event.data, citations.value.length)}，分数 ${formatScore(event.data.score)}`,
            })
          }
        }
        if (event.event === 'done') {
          runMeta.value = event.data
          traceCards.value = traceCards.value.map((card) => (card.status === 'running' ? { ...card, status: 'success' } : card))
          if (citations.value.length === 0) {
            traceCards.value.push({
              title: '知识库检索',
              status: 'warning',
              detail: '未命中知识库或当前智能体未绑定知识库，本次回答没有使用引用出处。',
            })
          }
          traceCards.value.push({
            title: '生成回答',
            status: 'success',
            detail: `trace_id ${event.data.trace_id || '无'} · Token ${event.data.usage?.total_tokens || 0}`,
          })
        }
        if (event.event === 'error') {
          const detail = friendlyChatError(event.data.detail || '请求失败')
          assistant.text += `\n${detail}`
          traceCards.value.push({ title: '运行错误', status: 'error', detail })
        }
      }
    }
  } finally {
    streaming.value = false
  }
}

async function openCitation(citation: Citation) {
  selectedCitation.value = citation
  citationDrawer.value = true
  citationContextChunks.value = []
  if (!citation.doc_id) return
  citationContextLoading.value = true
  try {
    citationContextChunks.value = await apiFetch<KnowledgeChunk[]>(`/documents/${citation.doc_id}/chunks`)
  } finally {
    citationContextLoading.value = false
  }
}

function renderMarkdown(text: string) {
  return md.render(text || '')
}

function handleMarkdownClick(event: MouseEvent) {
  const target = event.target
  if (!(target instanceof HTMLElement) || !target.classList.contains('markdown-copy')) return
  const block = target.closest('.markdown-codeblock')
  const code = block?.querySelector('code')?.textContent || ''
  if (!code) return
  window.navigator.clipboard?.writeText(code)
  target.textContent = '已复制'
  window.setTimeout(() => {
    target.textContent = '复制'
  }, 1200)
}

function copyCitationSnippet() {
  if (selectedCitation.value?.snippet) {
    window.navigator.clipboard?.writeText(selectedCitation.value.snippet)
  }
}

function citationTitle(citation: Citation, index: number) {
  const seq = citation.seq == null ? '-' : `#${citation.seq}`
  return `${citation.doc_name || `引用 ${index}`} · 切片 ${seq}`
}

function formatScore(value: number | null | undefined, digits = 3) {
  return value == null ? '-' : Number(value).toFixed(digits)
}

function formatChannels(channels: Citation['match_channels']) {
  if (!channels?.length) return '未知'
  return channels.map((channel) => (channel === 'vector' ? '向量' : channel === 'keyword' ? '关键词' : channel)).join(' / ')
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
            <EmptyState v-if="messages.length === 0" title="还没有对话" description="选择智能体后即可发送问题。若没有可用模型，请先在模型中心配置模型 API 并测试连通。" />
            <div v-for="(message, index) in messages" :key="index" class="message" :class="{ user: message.role === 'user' }">
              <strong>{{ message.role === 'user' ? '我' : '智能体' }}</strong>
              <div v-if="message.role === 'user'" class="message-text">{{ message.text }}</div>
              <div
                v-else
                class="markdown-body"
                @click="handleMarkdownClick"
                v-html="renderMarkdown(message.text || (streaming ? '生成中...' : ''))"
              />
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
          <el-alert
            v-if="citations.length > 0"
            :title="`引用 ${citations.length} 条，点击引用可定位来源文档和切片。`"
            type="info"
            :closable="false"
          />
          <el-alert
            v-else-if="runMeta"
            title="未命中知识库或当前智能体未绑定知识库，本次回答没有使用引用出处。"
            type="warning"
            :closable="false"
          />
          <article v-for="(citation, index) in citations" :key="citation.chunk_id || index" class="result-card">
            <div class="result-meta">
              <strong>{{ citationTitle(citation, index + 1) }}</strong>
              <StatusTag v-if="citation.score != null" status="success" :label="`RRF ${formatScore(citation.score)}`" />
              <StatusTag v-if="citation.vector_score != null" status="processing" :label="`向量 ${formatScore(citation.vector_score)}`" />
              <StatusTag v-if="citation.text_score != null" status="neutral" :label="`关键词 ${formatScore(citation.text_score)}`" />
              <span class="mono-id">{{ formatChannels(citation.match_channels) }}</span>
              <span v-if="citation.chunk_id" class="mono-id">{{ citation.chunk_id }}</span>
            </div>
            <p>{{ citation.snippet }}</p>
            <el-button size="small" @click="openCitation(citation)">定位来源 [{{ index + 1 }}]</el-button>
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
          <el-descriptions-item label="切片序号">{{ selectedCitation.seq == null ? '-' : `#${selectedCitation.seq}` }}</el-descriptions-item>
          <el-descriptions-item label="综合排名分">{{ formatScore(selectedCitation.score) }}</el-descriptions-item>
          <el-descriptions-item label="向量相似度">{{ formatScore(selectedCitation.vector_score) }}</el-descriptions-item>
          <el-descriptions-item label="关键词分">{{ formatScore(selectedCitation.text_score) }}</el-descriptions-item>
          <el-descriptions-item label="匹配通道">{{ formatChannels(selectedCitation.match_channels) }}</el-descriptions-item>
          <el-descriptions-item label="片段 ID">{{ selectedCitation.chunk_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="文档 ID">{{ selectedCitation.doc_id || '-' }}</el-descriptions-item>
        </el-descriptions>
        <section class="result-card">
          <strong>命中片段</strong>
          <p>{{ selectedCitation.snippet }}</p>
        </section>
        <section class="result-card">
          <strong>文档切片定位</strong>
          <p class="muted">显示当前文档的切片列表，当前引用片段会高亮。</p>
          <div v-loading="citationContextLoading" class="citation-context">
            <article
              v-for="chunk in citationContextChunks"
              :key="chunk.id"
              class="context-chunk"
              :class="{ active: chunk.id === selectedCitation.chunk_id }"
            >
              <div class="result-meta">
                <strong>切片 #{{ chunk.seq ?? '-' }}</strong>
                <span class="mono-id">{{ chunk.id }}</span>
              </div>
              <p>{{ chunk.content }}</p>
            </article>
            <EmptyState
              v-if="!citationContextLoading && citationContextChunks.length === 0"
              title="无法加载切片上下文"
              description="该引用只返回了片段摘要，暂时无法定位完整切片。"
            />
          </div>
        </section>
        <div class="form-actions">
          <el-button disabled>文档定位已显示在上方</el-button>
          <el-button type="primary" @click="copyCitationSnippet">复制原文</el-button>
        </div>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.citation-context {
  display: grid;
  gap: var(--space-3);
  margin-top: var(--space-3);
}

.context-chunk {
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  background: var(--color-bg-card);
}

.context-chunk.active {
  border-color: var(--color-brand-primary);
  background: rgba(37, 99, 235, 0.08);
  box-shadow: var(--shadow-card);
}

.context-chunk p {
  margin: var(--space-3) 0 0;
  white-space: pre-wrap;
  line-height: 1.7;
}
</style>
