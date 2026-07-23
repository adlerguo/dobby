<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { apiFetch } from '../api/client'
import type { AgentTemplate } from '../api/types'

const router = useRouter()
const templates = ref<AgentTemplate[]>([])
const keyword = ref('')
const activeCategory = ref('全部')
const preview = ref<AgentTemplate | null>(null)

const categories = ['全部', '政务服务', '企业办公', '售前支撑', '运维助手', '合同审查', '知识库问答', '工具调用']

const templateCards = computed(() =>
  templates.value
    .map((template) => {
      const ui = (template.default_config?.ui || {}) as Record<string, any>
      const persona = template.persona || String(template.default_config?.persona || '')
      const category = ui.category || categoryFromType(template.type)
      const description = ui.description || persona || '适合快速创建一个面向业务任务的 AI 助手。'
      const sampleQuestions = ui.sample_questions || ['这个助手适合什么场景？', '如何配置知识库？', '如何验证效果？']
      return { template, category, description, sampleQuestions }
    })
    .filter((item) => activeCategory.value === '全部' || item.category === activeCategory.value)
    .filter((item) => {
      const text = `${item.template.name} ${item.template.type} ${item.category} ${item.description}`.toLowerCase()
      return text.includes(keyword.value.trim().toLowerCase())
    }),
)

function categoryFromType(type: string) {
  if (type === 'qa' || type === 'retrieve') return '知识库问答'
  if (type === 'nl2data' || type === 'analysis') return '企业办公'
  if (type === 'doc_check') return '合同审查'
  if (type === 'ops_assistant') return '运维助手'
  if (type.includes('tool')) return '工具调用'
  return '政务服务'
}

function createFromTemplate(template: AgentTemplate) {
  router.push({ path: '/agents', query: { template_id: template.id } })
}

onMounted(async () => {
  templates.value = await apiFetch<AgentTemplate[]>('/agent-templates')
  preview.value = templates.value[0] || null
})
</script>

<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h1>模板广场</h1>
        <p>按业务场景浏览智能体模板，选择合适模板后即可进入创建向导。</p>
      </div>
      <el-input v-model="keyword" style="max-width: 340px" placeholder="搜索场景、部门、能力" />
    </div>

    <el-tabs v-model="activeCategory">
      <el-tab-pane v-for="category in categories" :key="category" :label="category" :name="category" />
    </el-tabs>

    <div class="template-layout">
      <section class="template-list-pane">
        <div class="template-grid gallery-grid">
          <article v-for="item in templateCards" :key="item.template.id" class="template-card">
            <div class="card-body">
              <h3>{{ item.template.name }}</h3>
              <p>{{ item.description }}</p>
              <div class="tag-row">
                <el-tag effect="plain">{{ item.category }}</el-tag>
                <el-tag effect="plain">{{ item.template.type }}</el-tag>
                <el-tag effect="plain">知识库问答</el-tag>
                <el-tag effect="plain">引用回答</el-tag>
              </div>
              <div class="template-questions">
                <p class="muted">示例问题</p>
                <ul>
                  <li v-for="question in item.sampleQuestions.slice(0, 3)" :key="question">{{ question }}</li>
                </ul>
              </div>
            </div>
            <div class="card-actions">
              <el-button @click="preview = item.template">预览</el-button>
              <el-button type="primary" @click="createFromTemplate(item.template)">从模板创建</el-button>
            </div>
          </article>
        </div>
      </section>

      <aside class="panel-card preview-pane">
        <div class="card-header">
          <h2>模板预览</h2>
        </div>
        <div v-if="preview" class="stack">
          <h3>{{ preview.name }}</h3>
          <p class="muted">这个模板会提供默认提示词、推荐问题、知识库配置和对话验证入口。</p>
          <el-collapse>
            <el-collapse-item title="原始数据（开发者）" name="raw-data">
              <pre>{{ JSON.stringify(preview.default_config || {}, null, 2) }}</pre>
            </el-collapse-item>
          </el-collapse>
          <div class="card-actions">
            <el-button type="primary" @click="createFromTemplate(preview)">使用这个模板</el-button>
          </div>
        </div>
        <div v-else class="empty">请在左侧选择一个模板，查看适用场景与创建入口。</div>
      </aside>
    </div>
  </section>
</template>
