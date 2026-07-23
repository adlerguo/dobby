<script setup lang="ts">
import { Database, MessageSquareText, PlugZap, UploadCloud } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'

import { apiFetch } from '../api/client'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import GuideBrowser from '../components/guide/GuideBrowser.vue'
import type { Agent, KnowledgeBase, KnowledgeDocument, ModelChannel, ModelHub } from '../api/types'

type StepState = 'done' | 'next' | 'todo'

const loading = ref(false)
const hasUsableModelChannel = ref(false)
const hasKnowledgeBase = ref(false)
const hasParsedDocument = ref(false)
const hasUsableAgent = ref(false)

const steps = computed(() => {
  const rows = [
  {
    title: '第一步：接入模型',
    desc: '接入对话模型与向量模型，接入时会自动测试连通，未通过不会启用。',
    to: '/model-hub',
    action: '去模型中心',
    icon: PlugZap,
    done: hasUsableModelChannel.value,
  },
  {
    title: '第二步：创建知识库',
    desc: '为智能体准备企业专属资料库；创建后可持续上传文档。',
    to: '/kbs',
    action: '去知识库实验台',
    icon: Database,
    done: hasKnowledgeBase.value,
  },
  {
    title: '第三步：上传资料',
    desc: '上传企业文档并等待解析完成，作为智能体回答的依据。',
    to: '/kbs',
    action: '上传资料',
    icon: UploadCloud,
    done: hasParsedDocument.value,
  },
  {
    title: '第四步：体验问答',
    desc: '创建智能体并绑定知识库，在对话中查看回答与其引用来源。',
    to: hasUsableAgent.value ? '/chat' : '/agents',
    action: hasUsableAgent.value ? '去对话验证' : '创建智能体',
    icon: MessageSquareText,
    done: hasUsableAgent.value,
  },
  ]
  const firstTodo = rows.findIndex((step) => !step.done)
  return rows.map((step, index) => {
    const state: StepState = step.done ? 'done' : index === firstTodo ? 'next' : 'todo'
    return { ...step, state }
  })
})

async function loadStatus() {
  loading.value = true
  try {
    const [models, kbs, agents] = await Promise.all([
      apiFetch<ModelHub[]>('/model-hub/models?limit=100'),
      apiFetch<KnowledgeBase[]>('/kbs'),
      apiFetch<Agent[]>('/agents'),
    ])
    const activeModels = models.filter((model) => model.is_active !== false)
    const channelGroups = await Promise.all(
      activeModels.map((model) => apiFetch<ModelChannel[]>(`/model-hub/models/${model.id}/channels`).catch(() => [])),
    )
    hasUsableModelChannel.value = channelGroups
      .flat()
      .some((channel) => channel.status === 'active' && channel.health !== 'failed')

    const activeKbs = kbs.filter((kb) => kb.status !== 'archived')
    hasKnowledgeBase.value = activeKbs.length > 0
    const documents = (
      await Promise.all(activeKbs.map((kb) => apiFetch<KnowledgeDocument[]>(`/kbs/${kb.id}/documents`).catch(() => [])))
    ).flat()
    hasParsedDocument.value = documents.some((document) => document.parse_status === 'done')
    hasUsableAgent.value = agents.some((agent) => agent.status === 'active')
  } finally {
    loading.value = false
  }
}

function stateLabel(state: StepState) {
  if (state === 'done') return '已完成'
  if (state === 'next') return '下一步'
  return '待处理'
}

function stateType(state: StepState) {
  if (state === 'done') return 'success'
  if (state === 'next') return 'warning'
  return 'info'
}

onMounted(loadStatus)
</script>

<template>
  <section class="page quickstart-page">
    <PageHeader
      title="快速开始"
      description="本平台帮助企业零门槛构建专属 AI 助手。按以下四步，即可完成从接入模型到上线问答的完整流程。"
    >
      <template #actions>
        <el-button :loading="loading" @click="loadStatus">刷新状态</el-button>
        <RouterLink class="el-button el-button--primary" to="/guide">查看完整教程</RouterLink>
      </template>
    </PageHeader>

    <el-alert
      class="quickstart-alert"
      type="warning"
      :closable="false"
      title="开始前，请先在模型中心接入至少一个对话模型与一个向量模型。"
    />

    <div v-loading="loading" class="quickstart-grid">
      <article v-for="(step, index) in steps" :key="step.title" class="quickstart-card">
        <div class="quickstart-card__index">{{ index + 1 }}</div>
        <component :is="step.icon" class="quickstart-card__icon" :size="24" />
        <div class="quickstart-card__body">
          <div class="quickstart-card__head">
            <h2>{{ step.title }}</h2>
            <el-tag :type="stateType(step.state)" effect="plain">{{ stateLabel(step.state) }}</el-tag>
          </div>
          <p>{{ step.desc }}</p>
        </div>
        <RouterLink class="el-button el-button--primary quickstart-card__action" :to="step.to">
          {{ step.action }}
        </RouterLink>
      </article>
    </div>

    <section class="quickstart-guide">
      <SectionHeader title="使用教程" description="按分类查看完整操作说明，在本页内切换文章即可阅读。" />
      <GuideBrowser embedded />
    </section>
  </section>
</template>

<style scoped>
.quickstart-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.quickstart-alert {
  max-width: 980px;
}

.quickstart-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
}

.quickstart-card {
  position: relative;
  min-height: 260px;
  padding: var(--space-5);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.quickstart-card__index {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-sidebar-active);
  color: var(--color-brand-secondary);
  font-weight: 700;
}

.quickstart-card__icon {
  color: var(--color-brand-secondary);
}

.quickstart-card__body {
  flex: 1;
}

.quickstart-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.quickstart-card h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.quickstart-card p {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.quickstart-card__action {
  width: fit-content;
}

.quickstart-guide {
  display: grid;
  gap: var(--space-4);
}

code {
  font-family: var(--font-family-mono);
  background: var(--color-bg-subtle);
  border-radius: var(--radius-sm);
  padding: 2px 6px;
}

@media (max-width: 1200px) {
  .quickstart-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .quickstart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
