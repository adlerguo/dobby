<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { apiFetch } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'
import type { KnowledgeBase, RetrieveOut } from '../api/types'

const kbs = ref<KnowledgeBase[]>([])
const loading = ref(false)
const creating = ref(false)
const retrieving = ref(false)
const query = ref('合同 审批')
const topK = ref(5)
const scoreThreshold = ref(0.4)
const retrieveMode = ref('hybrid')
const rerankEnabled = ref(false)
const activeKb = ref<KnowledgeBase | null>(null)
const retrieveResult = ref<RetrieveOut | null>(null)
const resultChunks = computed(() => retrieveResult.value?.chunks || [])
const resultCitations = computed(() => retrieveResult.value?.citations || [])
const form = ref({
  name: 'Vue 测试知识库',
  type: 'doc_regulation',
  description: '用于 Vue 工作台联调的知识库。',
})

async function loadKbs() {
  loading.value = true
  try {
    kbs.value = await apiFetch<KnowledgeBase[]>('/kbs')
  } finally {
    loading.value = false
  }
}

async function createKb() {
  creating.value = true
  try {
    await apiFetch<KnowledgeBase>('/kbs', {
      method: 'POST',
      body: {
        ...form.value,
        config: {},
        embedding_model: 'mock-embedding',
      },
    })
    await loadKbs()
  } finally {
    creating.value = false
  }
}

async function retrieveKb(kb: KnowledgeBase) {
  activeKb.value = kb
  retrieving.value = true
  retrieveResult.value = null
  try {
    retrieveResult.value = await apiFetch<RetrieveOut>(`/kbs/${kb.id}/retrieve`, {
      method: 'POST',
      body: { query: query.value || '合同 审批', top_k: topK.value },
    })
  } finally {
    retrieving.value = false
  }
}

function chunkTitle(index: number) {
  const citation = retrieveResult.value?.citations[index]
  return citation?.doc_name || `片段 ${index + 1}`
}

onMounted(loadKbs)
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
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <StatusTag :status="row.status || 'active'" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <el-button size="small" @click="retrieveKb(row)">检索</el-button>
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
            v-if="retrieveResult && resultChunks[0]?.score != null && Number(resultChunks[0].score) < scoreThreshold"
            title="最高命中分偏低，建议检查文档是否入库成功，或调低分块大小、增加关键词、开启 Query Rewrite / Rerank。"
            type="warning"
            :closable="false"
          />
          <article v-for="(chunk, index) in resultChunks" :key="chunk.id || chunk.chunk_id || index" class="result-card">
            <div class="result-meta">
              <strong>命中片段 {{ index + 1 }} · {{ chunkTitle(index) }}</strong>
              <StatusTag v-if="chunk.score != null" status="success" :label="`分数 ${Number(chunk.score).toFixed(3)}`" />
              <StatusTag status="info" :label="retrieveMode" />
              <span class="mono-id">{{ resultCitations[index]?.chunk_id || chunk.chunk_id || chunk.id }}</span>
            </div>
            <p>{{ chunk.content || chunk.snippet || resultCitations[index]?.snippet || '后端返回了命中片段，但没有携带正文。' }}</p>
            <el-button size="small">查看上下文</el-button>
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
  </section>
</template>
