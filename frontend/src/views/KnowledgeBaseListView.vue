<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { apiFetch, apiUpload } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'
import type { KnowledgeBase, KnowledgeChunk, KnowledgeDocument, Model, ReindexOut, RetrieveOut } from '../api/types'

const kbs = ref<KnowledgeBase[]>([])
const loading = ref(false)
const creating = ref(false)
const retrieving = ref(false)
const documentsLoading = ref(false)
const chunksLoading = ref(false)
const uploading = ref(false)
const savingKb = ref(false)
const reindexing = ref(false)
const documentDrawerVisible = ref(false)
const kbSettingsVisible = ref(false)
const contextDialogVisible = ref(false)
const contextLoading = ref(false)
const query = ref('合同 审批')
const topK = ref(5)
const scoreThreshold = ref(0)
const retrieveMode = ref('hybrid')
const rerankEnabled = ref(false)
const activeKb = ref<KnowledgeBase | null>(null)
const selectedKb = ref<KnowledgeBase | null>(null)
const editingKb = ref<KnowledgeBase | null>(null)
const selectedChunkDocument = ref<KnowledgeDocument | null>(null)
const selectedContextChunkId = ref('')
const contextChunks = ref<KnowledgeChunk[]>([])
const embeddingModels = ref<Model[]>([])
const documents = ref<KnowledgeDocument[]>([])
const docsByKb = ref<Record<string, KnowledgeDocument[]>>({})
const documentChunks = ref<KnowledgeChunk[]>([])
const expandedChunkIds = ref<Set<string>>(new Set())
const fileInput = ref<HTMLInputElement | null>(null)
let documentPollingTimer: number | undefined
const retrieveResult = ref<RetrieveOut | null>(null)
const resultChunks = computed(() => retrieveResult.value?.chunks || [])
const resultCitations = computed(() => retrieveResult.value?.citations || [])
const supportedFileAccept =
  '.txt,.md,.pdf,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const terminalParseStatuses = new Set(['done', 'failed'])
const activeDocuments = computed(() => (activeKb.value ? docsByKb.value[activeKb.value.id] || [] : []))
const activeDocumentsKnown = computed(() => Boolean(activeKb.value && Object.prototype.hasOwnProperty.call(docsByKb.value, activeKb.value.id)))
const activeHasNoDoneDocuments = computed(() => Boolean(activeDocumentsKnown.value && !activeDocuments.value.some(isDoneDocument)))
const chunkSummary = computed(() => {
  const count = documentChunks.value.length
  const averageLength = count
    ? Math.round(documentChunks.value.reduce((total, chunk) => total + Number(chunk.content_length || chunk.content.length), 0) / count)
    : 0
  const method = String(documentChunks.value[0]?.meta?.chunk_method || '-')
  return { count, averageLength, method }
})
const selectedContextChunk = computed(() => contextChunks.value.find((chunk) => chunk.id === selectedContextChunkId.value) || null)
const form = ref({
  name: 'Vue 测试知识库',
  type: 'doc_regulation',
  description: '用于 Vue 工作台联调的知识库。',
})
const settingsForm = ref({
  embedding_model: 'mock-embedding',
})

async function loadKbs() {
  loading.value = true
  try {
    kbs.value = await apiFetch<KnowledgeBase[]>('/kbs')
  } finally {
    loading.value = false
  }
}

async function loadEmbeddingModels() {
  const models = await apiFetch<Model[]>('/models')
  embeddingModels.value = models.filter((model) => model.type === 'embedding')
}

async function createKb() {
  creating.value = true
  try {
    const kb = await apiFetch<KnowledgeBase>('/kbs', {
      method: 'POST',
      body: {
        ...form.value,
        config: {},
        embedding_model: 'mock-embedding',
      },
    })
    await loadKbs()
    ElMessage.success('知识库已创建。下一步：上传文档开始构建知识库。')
    await openDocumentPanel(kb)
  } catch (error) {
    ElMessage.error(formatKbError(error))
  } finally {
    creating.value = false
  }
}

function openKbSettings(kb: KnowledgeBase) {
  editingKb.value = kb
  settingsForm.value = {
    embedding_model: kb.embedding_model || 'mock-embedding',
  }
  kbSettingsVisible.value = true
}

async function saveKbSettings() {
  if (!editingKb.value) return
  const oldModel = editingKb.value.embedding_model || 'mock-embedding'
  const nextModel = settingsForm.value.embedding_model || 'mock-embedding'
  if (oldModel !== nextModel) {
    await ElMessageBox.confirm(
      '仅空知识库允许更换 embedding 模型。已有文档的知识库会在后端拒绝切换，避免旧维度切片被孤立导致文档存在但检索不到。',
      '确认更换 embedding 模型',
      { confirmButtonText: '继续保存', cancelButtonText: '取消', type: 'warning' },
    )
  }

  savingKb.value = true
  try {
    const updated = await apiFetch<KnowledgeBase>(`/kbs/${editingKb.value.id}`, {
      method: 'PATCH',
      body: { embedding_model: nextModel },
    })
    kbs.value = kbs.value.map((kb) => (kb.id === updated.id ? updated : kb))
    if (selectedKb.value?.id === updated.id) selectedKb.value = updated
    if (activeKb.value?.id === updated.id) activeKb.value = updated
    editingKb.value = updated
    kbSettingsVisible.value = false
    ElMessage.success('知识库设置已保存')
  } catch (error) {
    ElMessage.error(formatKbError(error))
  } finally {
    savingKb.value = false
  }
}

async function reindexKb(kb: KnowledgeBase) {
  await ElMessageBox.confirm(
    '重建索引会重新解析已完成文档，并使用当前 embedding 模型重新生成向量。重建期间旧索引仍保留，完成后替换。',
    '确认重建索引',
    { confirmButtonText: '开始重建', cancelButtonText: '取消', type: 'warning' },
  )
  reindexing.value = true
  try {
    const result = await apiFetch<ReindexOut>(`/kbs/${kb.id}/reindex`, {
      method: 'POST',
      body: {},
    })
    ElMessage.success(`已提交重建任务，共 ${result.document_count} 个文档`)
    if (selectedKb.value?.id === kb.id) {
      await loadDocumentsForKb(kb.id)
      refreshDocumentPolling()
    }
  } catch (error) {
    ElMessage.error(formatKbError(error))
  } finally {
    reindexing.value = false
  }
}

async function retrieveKb(kb: KnowledgeBase) {
  activeKb.value = kb
  retrieving.value = true
  retrieveResult.value = null
  try {
    await loadDocumentsForKb(kb.id, { silent: true })
    retrieveResult.value = await apiFetch<RetrieveOut>(`/kbs/${kb.id}/retrieve`, {
      method: 'POST',
      body: {
        query: query.value || '合同 审批',
        top_k: topK.value,
        match_type: retrieveMode.value,
        score_threshold: scoreThreshold.value,
      },
    })
  } catch (error) {
    ElMessage.error(formatKbError(error))
  } finally {
    retrieving.value = false
  }
}

async function openDocumentPanel(kb: KnowledgeBase) {
  selectedKb.value = kb
  documentDrawerVisible.value = true
  clearChunks()
  await loadDocumentsForKb(kb.id)
  refreshDocumentPolling()
}

async function loadDocumentsForKb(kbId: string, options: { silent?: boolean } = {}) {
  if (!options.silent) documentsLoading.value = true
  try {
    const result = await apiFetch<KnowledgeDocument[]>(`/kbs/${kbId}/documents`)
    docsByKb.value = { ...docsByKb.value, [kbId]: result }
    if (selectedKb.value?.id === kbId) documents.value = result
    return result
  } finally {
    if (!options.silent) documentsLoading.value = false
  }
}

function triggerUpload() {
  fileInput.value?.click()
}

async function handleFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !selectedKb.value) return

  const formData = new FormData()
  formData.append('file', file)
  uploading.value = true
  try {
    await apiUpload<KnowledgeDocument>(`/kbs/${selectedKb.value.id}/documents`, formData)
    ElMessage.success('文档已上传，正在解析')
    await loadDocumentsForKb(selectedKb.value.id)
    refreshDocumentPolling()
  } catch (error) {
    ElMessage.error(formatKbError(error))
  } finally {
    uploading.value = false
  }
}

async function loadDocumentChunks(document: KnowledgeDocument) {
  selectedChunkDocument.value = document
  chunksLoading.value = true
  expandedChunkIds.value = new Set()
  try {
    documentChunks.value = await apiFetch<KnowledgeChunk[]>(`/documents/${document.id}/chunks`)
  } catch (error) {
    ElMessage.error(formatKbError(error))
  } finally {
    chunksLoading.value = false
  }
}

async function openHitContext(chunk: { id?: string; chunk_id?: string; doc_id?: string; seq?: number | null }) {
  const docId = chunk.doc_id
  const chunkId = chunk.id || chunk.chunk_id || ''
  if (!docId) {
    ElMessage.warning('当前命中结果没有文档 ID，无法查看上下文')
    return
  }

  selectedContextChunkId.value = chunkId
  contextDialogVisible.value = true
  contextLoading.value = true
  try {
    const allChunks = await apiFetch<KnowledgeChunk[]>(`/documents/${docId}/chunks`)
    const current = allChunks.find((item) => item.id === chunkId || item.seq === chunk.seq)
    if (!current || current.seq == null) {
      contextChunks.value = current ? [current] : []
      return
    }
    contextChunks.value = allChunks.filter((item) => item.seq != null && Math.abs(Number(item.seq) - Number(current.seq)) <= 1)
  } catch (error) {
    ElMessage.error(formatKbError(error))
  } finally {
    contextLoading.value = false
  }
}

function refreshDocumentPolling() {
  stopDocumentPolling()
  if (!selectedKb.value || !hasProcessingDocuments(documents.value)) return
  documentPollingTimer = window.setInterval(async () => {
    if (!selectedKb.value) {
      stopDocumentPolling()
      return
    }
    const nextDocuments = await loadDocumentsForKb(selectedKb.value.id, { silent: true })
    if (!hasProcessingDocuments(nextDocuments)) {
      stopDocumentPolling()
    }
  }, 2500)
}

function stopDocumentPolling() {
  if (documentPollingTimer) {
    window.clearInterval(documentPollingTimer)
    documentPollingTimer = undefined
  }
}

function hasProcessingDocuments(items: KnowledgeDocument[]) {
  return items.some((item) => !terminalParseStatuses.has(String(item.parse_status || 'pending')))
}

function isDoneDocument(item: KnowledgeDocument) {
  return item.parse_status === 'done'
}

function documentStatusLabel(status: string | null | undefined) {
  const labels: Record<string, string> = {
    pending: '待处理',
    parsing: '解析中',
    done: '完成',
    failed: '失败',
  }
  return labels[String(status || 'pending')] || String(status || '待处理')
}

function documentStatusSemantic(status: string | null | undefined) {
  const map: Record<string, string> = {
    pending: 'neutral',
    parsing: 'parsing',
    done: 'done',
    failed: 'failed',
  }
  return map[String(status || 'pending')] || 'neutral'
}

function clearChunks() {
  selectedChunkDocument.value = null
  documentChunks.value = []
  expandedChunkIds.value = new Set()
}

function chunkPreview(content: string) {
  return content.length > 200 ? `${content.slice(0, 200)}...` : content
}

function isChunkExpanded(chunkId: string) {
  return expandedChunkIds.value.has(chunkId)
}

function toggleChunk(chunkId: string) {
  const next = new Set(expandedChunkIds.value)
  if (next.has(chunkId)) {
    next.delete(chunkId)
  } else {
    next.add(chunkId)
  }
  expandedChunkIds.value = next
}

function formatSize(size: number | null | undefined) {
  if (!size) return '-'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(value: string | null | undefined) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function formatKbError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || '请求失败')
  const map: Record<string, string> = {
    kb_name_exists: '知识库名称已存在',
    document_name_exists: '该知识库中已存在同名文档',
    unsupported_document_type: '暂不支持该文件类型，请上传 txt、md、pdf 或 docx',
    kb_not_found: '知识库不存在或已归档',
    kb_embedding_model_locked_has_documents: '该知识库已有文档，embedding 模型和维度已锁定。请新建知识库并重新上传文档。',
  }
  return map[message] || message
}

function chunkTitle(index: number) {
  const citation = retrieveResult.value?.citations[index]
  return citation?.doc_name || `片段 ${index + 1}`
}

function formatScore(value: number | null | undefined, digits = 3) {
  if (value == null) return '未命中该通道'
  return Number(value).toFixed(digits)
}

function channelLabel(channel: string) {
  const labels: Record<string, string> = {
    vector: '向量',
    keyword: '关键词',
  }
  return labels[channel] || channel
}

function highestVectorScore() {
  const scores = resultChunks.value
    .map((chunk) => chunk.vector_score)
    .filter((score): score is number => score != null)
  return scores.length ? Math.max(...scores) : null
}

function shouldShowVectorWarning() {
  const score = highestVectorScore()
  return retrieveResult.value && retrieveMode.value !== 'keyword' && score != null && score < 0.5
}

onMounted(async () => {
  await Promise.all([loadKbs(), loadEmbeddingModels()])
})
onUnmounted(stopDocumentPolling)

watch(documentDrawerVisible, (visible) => {
  if (!visible) {
    stopDocumentPolling()
    clearChunks()
  }
})
</script>

<template>
  <section class="business-page">
    <PageHeader title="知识库实验台" description="管理知识库并直接测试召回片段、来源和分数。">
      <template #actions>
        <el-button @click="loadKbs">刷新</el-button>
      </template>
    </PageHeader>

    <div class="grid two">
      <section class="panel-card">
        <SectionHeader title="知识库列表" description="查看知识库状态并进入命中测试。" />
        <el-table v-loading="loading" :data="kbs" border>
          <template #empty>
            <EmptyState title="还没有知识库" description="创建知识库后可上传文档并进行召回测试。" action-text="创建知识库" @action="createKb" />
          </template>
          <el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column prop="type" label="类型" width="140" />
          <el-table-column prop="embedding_model" label="Embedding" width="180">
            <template #default="{ row }">
              <span class="mono-id">{{ row.embedding_model || 'mock-embedding' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="维度" width="90">
            <template #default="{ row }">
              <span class="mono-id">{{ row.embedding_dim || 1536 }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <StatusTag :status="row.status || 'active'" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="280" align="right">
            <template #default="{ row }">
              <el-button size="small" @click="retrieveKb(row)">检索</el-button>
              <el-button size="small" type="primary" plain @click="openDocumentPanel(row)">文档</el-button>
              <el-button size="small" @click="openKbSettings(row)">设置</el-button>
              <el-button size="small" :loading="reindexing" @click="reindexKb(row)">重建</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="panel-card">
        <SectionHeader title="创建知识库" description="先创建知识库容器，再上传文档入库。" />
        <el-form label-position="top">
          <el-form-item label="名称">
            <el-input v-model="form.name" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="form.type">
              <el-option label="制度文档" value="doc_regulation" />
              <el-option label="政策" value="policy" />
              <el-option label="FAQ" value="faq" />
              <el-option label="案例" value="case" />
              <el-option label="资料" value="material" />
            </el-select>
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="form.description" type="textarea" :rows="4" />
            <div class="field-help">用于区分业务范围，后续会显示在知识库详情中。</div>
          </el-form-item>
          <el-button type="primary" :loading="creating" @click="createKb">创建</el-button>
          <div class="field-help">创建成功后会直接进入文档管理，可继续上传 txt、md、pdf 或 docx。</div>
        </el-form>
      </section>
    </div>

    <section class="panel-card mt">
      <SectionHeader
        title="命中测试实验台"
        :description="activeKb ? `${activeKb.name} · 命中 ${resultChunks.length} 条片段` : '选择知识库后展示命中片段和来源。'"
      />
      <div class="grid two">
        <aside class="stack">
          <el-form label-position="top">
            <el-form-item label="测试问题">
              <el-input v-model="query" type="textarea" :rows="4" />
            </el-form-item>
            <el-form-item label="TopK">
              <el-slider v-model="topK" :min="1" :max="20" show-input />
            </el-form-item>
            <el-form-item label="Score Threshold">
              <div class="field-help">向量相似度阈值（仅过滤向量通道）；关键词-only 结果不受该阈值影响。</div>
              <el-slider v-model="scoreThreshold" :min="0" :max="1" :step="0.05" show-input />
            </el-form-item>
            <el-form-item label="检索模式">
              <el-segmented v-model="retrieveMode" :options="[
                { label: '向量', value: 'vector' },
                { label: '关键词', value: 'keyword' },
                { label: '混合', value: 'hybrid' },
              ]" />
            </el-form-item>
            <el-form-item label="Rerank">
              <el-switch v-model="rerankEnabled" active-text="开启" inactive-text="关闭" />
            </el-form-item>
            <el-button type="primary" :disabled="!activeKb" :loading="retrieving" @click="activeKb && retrieveKb(activeKb)">
              开始测试
            </el-button>
          </el-form>
        </aside>

        <div v-loading="retrieving" class="stack">
          <el-alert
            v-if="activeHasNoDoneDocuments"
            title="该知识库还没有解析完成的文档，检索将无结果。"
            type="warning"
            :closable="false"
          />
          <EmptyState
            v-if="!retrieveResult"
            title="还没有测试结果"
            description="点击知识库列表中的“检索”，或选择知识库后开始测试。"
          />
          <EmptyState
            v-else-if="resultChunks.length === 0"
            title="没有检索到匹配片段"
            description="可以调整问题、TopK 或阈值后再次测试。"
          />
          <el-alert
            v-if="shouldShowVectorWarning()"
            title="未检索到高相关内容（最高向量相似度低于 0.5），可能知识库中没有该问题相关的资料，或可尝试调整问题表述。"
            type="warning"
            :closable="false"
          />
          <article v-for="(chunk, index) in resultChunks" :key="chunk.id || chunk.chunk_id || index" class="result-card">
            <div class="result-meta">
              <strong>{{ chunk.doc_name || chunkTitle(index) }} · 切片 #{{ chunk.seq ?? '-' }}</strong>
              <StatusTag status="success" :label="`向量相似度 ${formatScore(chunk.vector_score)}`" />
              <StatusTag status="info" :label="`关键词分 ${formatScore(chunk.text_score)}`" />
              <el-tooltip content="RRF 排名分用于融合向量和关键词召回，单通道第一名约 0.016，双通道第一名约 0.0328，不是相似度。">
                <StatusTag status="neutral" :label="`RRF排名分 ${formatScore(chunk.score, 6)}`" />
              </el-tooltip>
              <StatusTag
                v-for="channel in chunk.match_channels || []"
                :key="channel"
                status="info"
                :label="channelLabel(channel)"
              />
              <span class="mono-id">{{ resultCitations[index]?.chunk_id || chunk.chunk_id || chunk.id }}</span>
            </div>
            <div class="field-help">内容长度：{{ chunk.content_length || chunk.content?.length || 0 }} 字符</div>
            <p>{{ chunk.content || chunk.snippet || resultCitations[index]?.snippet || '后端返回了命中片段，但没有携带正文。' }}</p>
            <el-button size="small" @click="openHitContext(chunk)">查看上下文</el-button>
          </article>
          <div v-if="retrieveResult" class="panel-card">
            <h3>调优建议</h3>
            <ul>
              <li>低分召回时，先确认文档解析和切片是否完成。</li>
              <li>业务问题较短时，可补充关键词或开启 query rewrite。</li>
              <li>结果重复时，建议开启父子分块或 rerank。</li>
            </ul>
          </div>
        </div>
      </div>
    </section>

    <el-drawer
      v-model="documentDrawerVisible"
      :title="selectedKb ? `${selectedKb.name} · 文档管理` : '文档管理'"
      size="720px"
      destroy-on-close
    >
      <section class="kb-docs-drawer">
        <SectionHeader
          title="文档列表"
          description="上传文档后系统会自动解析、切片并入库。"
        >
          <template #actions>
            <el-button @click="selectedKb && loadDocumentsForKb(selectedKb.id)" :loading="documentsLoading">刷新</el-button>
            <el-button type="primary" :loading="uploading" @click="triggerUpload">上传文档</el-button>
          </template>
        </SectionHeader>

        <input
          ref="fileInput"
          class="visually-hidden-file"
          type="file"
          :accept="supportedFileAccept"
          @change="handleFileSelected"
        />

        <el-alert
          title="支持 txt、md、pdf、docx；上传后会自动轮询解析状态，全部完成或失败后停止。"
          type="info"
          :closable="false"
        />

        <el-table v-loading="documentsLoading" :data="documents" border class="document-table">
          <template #empty>
            <EmptyState
              title="还没有文档"
              description="上传 txt、pdf、md 或 docx 文档开始构建知识库。"
              action-text="上传文档"
              @action="triggerUpload"
            />
          </template>
          <el-table-column label="文件名" min-width="220">
            <template #default="{ row }">
              <div class="document-name">
                <strong>{{ row.name }}</strong>
                <span>{{ row.mime || 'unknown' }} · {{ formatSize(row.size) }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="解析状态" width="120">
            <template #default="{ row }">
              <StatusTag :status="documentStatusSemantic(row.parse_status)" :label="documentStatusLabel(row.parse_status)" />
            </template>
          </el-table-column>
          <el-table-column label="上传时间" width="190">
            <template #default="{ row }">
              {{ formatDate(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" align="right">
            <template #default="{ row }">
              <el-button size="small" :disabled="row.parse_status !== 'done'" @click="loadDocumentChunks(row)">查看切片</el-button>
            </template>
          </el-table-column>
        </el-table>

        <section class="chunk-panel">
          <SectionHeader
            title="切片可视化"
            :description="selectedChunkDocument ? selectedChunkDocument.name : '选择已完成解析的文档查看切片结果。'"
          />

          <EmptyState
            v-if="!selectedChunkDocument"
            title="还没有选择文档"
            description="点击文档列表中的“查看切片”，即可查看序号、长度、向量状态和内容全文。"
          />

          <div v-else v-loading="chunksLoading" class="chunk-panel__body">
            <div v-if="documentChunks.length > 0" class="chunk-summary">
              <div>
                <span>共</span>
                <strong>{{ chunkSummary.count }}</strong>
                <span>片</span>
              </div>
              <div>
                <span>平均长度</span>
                <strong>{{ chunkSummary.averageLength }}</strong>
                <span>字符</span>
              </div>
              <div>
                <span>切分方法</span>
                <strong>{{ chunkSummary.method }}</strong>
              </div>
            </div>

            <EmptyState
              v-if="!chunksLoading && documentChunks.length === 0"
              title="该文档还没有切片"
              description="文档可能尚未解析完成，或解析失败未生成切片。"
            />

            <article v-for="chunk in documentChunks" :key="chunk.id" class="chunk-card">
              <div class="chunk-card__meta">
                <strong>切片 #{{ chunk.seq ?? '-' }}</strong>
                <StatusTag status="neutral" :label="`${chunk.content_length || chunk.content.length} 字符`" />
                <StatusTag :status="chunk.has_embedding" :label="chunk.has_embedding ? '已有向量' : '无向量'" />
                <span class="mono-id">{{ chunk.id }}</span>
              </div>
              <p class="chunk-card__content">
                {{ isChunkExpanded(chunk.id) ? chunk.content : chunkPreview(chunk.content) }}
              </p>
              <el-button v-if="chunk.content.length > 200" size="small" text @click="toggleChunk(chunk.id)">
                {{ isChunkExpanded(chunk.id) ? '收起' : '展开全文' }}
              </el-button>
            </article>
          </div>
        </section>
      </section>
    </el-drawer>

    <el-dialog v-model="kbSettingsVisible" title="知识库设置" width="520px">
      <el-form label-position="top">
        <el-form-item label="Embedding 模型">
          <el-select v-model="settingsForm.embedding_model" filterable>
            <el-option
              v-for="model in embeddingModels"
              :key="model.id"
              :label="model.name"
              :value="model.name"
            />
          </el-select>
          <div class="field-help">
            仅空知识库允许更换 embedding 模型。已有文档后模型和维度会锁定；如需更换，请新建知识库并重新上传文档。
          </div>
        </el-form-item>
        <el-alert
          title="系统会按所选 embedding 模型的真实维度写入知识库，当前支持 1024 / 1536 / 3072 维。3072 维暂不建 HNSW 索引，适合小型知识库；大库建议选择 1024/1536 维或将 large 模型 dimensions 降到 2000 以内。DeepSeek 不提供 embedding。"
          type="warning"
          :closable="false"
        />
      </el-form>
      <template #footer>
        <el-button @click="kbSettingsVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingKb" @click="saveKbSettings">保存设置</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="contextDialogVisible"
      :title="selectedContextChunk ? `切片上下文 · #${selectedContextChunk.seq ?? '-'}` : '切片上下文'"
      width="760px"
    >
      <section v-loading="contextLoading" class="chunk-panel__body">
        <EmptyState
          v-if="!contextLoading && contextChunks.length === 0"
          title="没有可展示的上下文"
          description="当前命中切片没有找到相邻切片，或文档切片尚未生成。"
        />
        <article
          v-for="chunk in contextChunks"
          :key="chunk.id"
          class="chunk-card"
          :class="{ 'chunk-card--active': chunk.id === selectedContextChunkId }"
        >
          <div class="chunk-card__meta">
            <strong>切片 #{{ chunk.seq ?? '-' }}</strong>
            <StatusTag status="neutral" :label="`${chunk.content_length || chunk.content.length} 字符`" />
            <StatusTag :status="chunk.has_embedding" :label="chunk.has_embedding ? '已有向量' : '无向量'" />
            <StatusTag v-if="chunk.id === selectedContextChunkId" status="success" label="当前命中" />
          </div>
          <p class="chunk-card__content">{{ chunk.content }}</p>
        </article>
      </section>
    </el-dialog>
  </section>
</template>
