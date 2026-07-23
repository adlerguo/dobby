<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { apiFetch, normalizeApiError } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'
import { useAgentsStore } from '../stores/agents'
import type { Agent, AgentRagConfig, AgentTemplate, KnowledgeBase, Model } from '../api/types'

const agentsStore = useAgentsStore()
const { agents } = storeToRefs(agentsStore)
const templates = ref<AgentTemplate[]>([])
const models = ref<Model[]>([])
const kbs = ref<KnowledgeBase[]>([])
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const creating = ref(false)
const updating = ref(false)
const activeTab = ref('list')
const activeStep = ref(0)
const form = ref({
  name: defaultAgentName(),
  type: 'qa',
  template_id: '',
  model_id: '',
  persona: '基于企业知识库回答问题，回答需给出引用。',
  kb_ids: [] as string[],
  rag: {
    top_k: 3,
    score_threshold: 0,
    match_type: 'hybrid',
  } as AgentRagConfig,
  answer_style_enabled: true,
})
const editVisible = ref(false)
const editingAgent = ref<Agent | null>(null)
const createdAgentId = ref('')
const editForm = ref({
  name: '',
  template_id: '',
  model_id: '',
  persona: '',
  kb_ids: [] as string[],
  rag: {
    top_k: 3,
    score_threshold: 0,
    match_type: 'hybrid',
  } as AgentRagConfig,
  answer_style_enabled: true,
})
const activeKbs = computed(() => kbs.value.filter((kb) => kb.status !== 'archived'))

async function loadData() {
  loading.value = true
  try {
    const [agentRows, templateRows, modelRows, kbRows] = await Promise.all([
      agentsStore.fetchAgents(),
      apiFetch<AgentTemplate[]>('/agent-templates'),
      apiFetch<Model[]>('/models'),
      apiFetch<KnowledgeBase[]>('/kbs'),
    ])
    templates.value = templateRows
    models.value = modelRows
    kbs.value = kbRows
    if (route.query.template_id && typeof route.query.template_id === 'string') {
      const selected = templates.value.find((template) => template.id === route.query.template_id)
      if (selected) {
        form.value.template_id = selected.id
        form.value.type = selected.type
        form.value.persona = selected.persona || String(selected.default_config?.persona || form.value.persona)
        activeTab.value = 'create'
      }
    }
  } finally {
    loading.value = false
  }
}

async function createAgent() {
  creating.value = true
  try {
    const created = await apiFetch<Agent>('/agents', {
      method: 'POST',
      body: {
        name: form.value.name,
        type: form.value.type,
        template_id: form.value.template_id || null,
        model_id: form.value.model_id || null,
        persona: form.value.persona,
        kb_ids: form.value.kb_ids,
        tool_ids: [],
        config: {
          temperature: 0.2,
          rag: normalizeRagConfig(form.value.rag),
          answer_style_enabled: form.value.answer_style_enabled,
        },
      },
    })
    agentsStore.upsertAgent(created)
    createdAgentId.value = created.id
    ElMessage.success('智能体已创建')
    await loadData()
    activeStep.value = 3
    await router.push(`/chat?agent_id=${created.id}`)
  } catch (error) {
    ElMessage.error(formatAgentError(error))
  } finally {
    creating.value = false
  }
}

function selectTemplate(template: AgentTemplate) {
  form.value.template_id = template.id
  form.value.type = template.type
  form.value.persona = template.persona || String(template.default_config?.persona || form.value.persona)
  activeStep.value = 1
}

function createBlankAgent() {
  form.value.template_id = ''
  form.value.type = 'qa'
  activeStep.value = 1
}

function goTemplateGallery() {
  router.push('/templates')
}

async function publishAgent(agent: Agent) {
  try {
    const updated = await apiFetch<Agent>(`/agents/${agent.id}/publish`, { method: 'POST', body: {} })
    agentsStore.upsertAgent(updated)
    ElMessage.success('智能体已发布')
    await loadData()
  } catch (error) {
    ElMessage.error(formatAgentError(error))
  }
}

async function deleteAgent(agent: Agent) {
  try {
    await apiFetch<null>(`/agents/${agent.id}`, { method: 'DELETE' })
    agentsStore.removeAgent(agent.id)
    ElMessage.success('智能体已删除')
    await loadData()
  } catch (error) {
    ElMessage.error(formatAgentError(error))
  }
}

function ragConfigFromAgent(agent: Agent): AgentRagConfig {
  const config = agent.config || {}
  const rag = typeof config.rag === 'object' && config.rag !== null ? (config.rag as Partial<AgentRagConfig>) : {}
  return normalizeRagConfig({
    top_k: rag.top_k ?? 3,
    score_threshold: rag.score_threshold ?? 0,
    match_type: rag.match_type ?? 'hybrid',
  })
}

function normalizeRagConfig(rag: Partial<AgentRagConfig>): AgentRagConfig {
  const topK = Number(rag.top_k)
  const threshold = Number(rag.score_threshold)
  const rawMatchType = rag.match_type || 'hybrid'
  const matchType = ['hybrid', 'vector', 'keyword'].includes(rawMatchType) ? rawMatchType : 'hybrid'
  return {
    top_k: Number.isFinite(topK) ? Math.min(Math.max(Math.round(topK), 1), 20) : 3,
    score_threshold: Number.isFinite(threshold) ? Math.min(Math.max(threshold, 0), 1) : 0,
    match_type: matchType as AgentRagConfig['match_type'],
  }
}

function openEdit(agent: Agent) {
  editingAgent.value = agent
  editForm.value = {
    name: agent.name,
    template_id: agent.template_id || '',
    model_id: agent.model_id || '',
    persona: agent.persona || '',
    kb_ids: [...(agent.kb_ids || [])],
    rag: ragConfigFromAgent(agent),
    answer_style_enabled: (agent.config?.answer_style_enabled as boolean | undefined) !== false,
  }
  editVisible.value = true
}

async function updateAgent() {
  if (!editingAgent.value) return
  updating.value = true
  try {
    const existingConfig = editingAgent.value.config || {}
    const updated = await apiFetch<Agent>(`/agents/${editingAgent.value.id}`, {
      method: 'PATCH',
      body: {
        name: editForm.value.name,
        template_id: editForm.value.template_id || null,
        model_id: editForm.value.model_id || null,
        persona: editForm.value.persona,
        kb_ids: editForm.value.kb_ids,
        config: {
          ...existingConfig,
          rag: normalizeRagConfig(editForm.value.rag),
          answer_style_enabled: editForm.value.answer_style_enabled,
        },
      },
    })
    agentsStore.upsertAgent(updated)
    ElMessage.success('智能体配置已更新')
    editVisible.value = false
    await loadData()
  } catch (error) {
    ElMessage.error(formatAgentError(error))
  } finally {
    updating.value = false
  }
}

function defaultAgentName() {
  const now = new Date()
  const stamp = `${now.getMonth() + 1}${now.getDate()}-${now.getHours()}${now.getMinutes()}${now.getSeconds()}`
  return `step2-ui-agent-${stamp}`
}

function formatAgentError(error: unknown) {
  const parsed = normalizeApiError(error)
  const map: Record<string, string> = {
    agent_name_exists: '智能体名称已存在，请换一个名称后重试。',
    model_not_found: '模型不存在，请重新选择模型。',
    agent_template_not_found: '模板不存在，请重新选择模板。',
    agent_template_type_mismatch: '模板类型和智能体类型不一致，请重新选择模板。',
    not_found: '智能体不存在或已归档。',
  }
  return map[parsed.code] || parsed.message
}

onMounted(loadData)
</script>

<template>
  <section class="business-page">
    <PageHeader title="智能体工厂" description="创建面向某类业务任务的 AI 助手，并为其配置模型、知识库与工具能力。">
      <template #actions>
        <el-button @click="router.push('/factory')">进入智能体工厂</el-button>
        <el-button @click="goTemplateGallery">模板广场</el-button>
        <el-button type="primary" @click="activeTab = 'create'">创建智能体</el-button>
      </template>
    </PageHeader>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="智能体列表" name="list" />
      <el-tab-pane label="创建向导" name="create" />
    </el-tabs>

    <section v-if="activeTab === 'list'" class="panel-card">
        <SectionHeader title="智能体列表" description="查看、编辑和发布当前企业已创建的智能体。">
          <template #actions>
            <el-button @click="loadData">刷新</el-button>
          </template>
        </SectionHeader>
        <el-table v-loading="loading" :data="agents" border>
          <template #empty>
            <EmptyState title="还没有智能体" description="请从模板或空白配置开始，创建第一个面向业务任务的 AI 助手。" action-text="创建智能体" @action="activeTab = 'create'" />
          </template>
          <el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column prop="type" label="类型" width="120" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <StatusTag :status="row.status === 'active' ? 'active' : 'draft'" :label="row.status === 'active' ? '可用' : '草稿'" />
            </template>
          </el-table-column>
          <el-table-column label="绑定" width="140">
            <template #default="{ row }">{{ row.kb_ids?.length || 0 }} KB / {{ row.tool_ids?.length || 0 }} 工具</template>
          </el-table-column>
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button v-if="row.status !== 'active'" size="small" @click="publishAgent(row)">发布</el-button>
              <StatusTag v-else status="active" label="可用" />
              <el-popconfirm title="确定删除这个智能体吗？" confirm-button-text="删除" cancel-button-text="取消" @confirm="deleteAgent(row)">
                <template #reference>
                  <el-button size="small" type="danger" text>删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </section>

    <section v-else class="panel-card">
        <SectionHeader title="创建智能体" description="按步骤选择创建方式、填写基础信息，并配置模型、知识库与工具能力。" />
        <el-steps :active="activeStep" finish-status="success" simple>
          <el-step title="选择模板" />
          <el-step title="基础信息" />
          <el-step title="能力配置" />
          <el-step title="验证效果" />
        </el-steps>

        <div v-if="activeStep === 0" class="wizard-step-intro mt">
          <h3>选择模板</h3>
          <p>选择一个场景模板快速开始，或从空白自定义创建。</p>
        </div>

        <div v-if="activeStep === 0" class="template-grid mt">
          <article
            class="template-card blank-template-card"
            role="button"
            tabindex="0"
            @click="createBlankAgent"
            @keydown.enter.prevent="createBlankAgent"
            @keydown.space.prevent="createBlankAgent"
          >
            <div>
              <h3>从空白创建</h3>
              <p>不使用模板，自行配置名称、类型、提示词、知识库与工具能力。</p>
            </div>
            <div class="tag-row">
              <el-tag effect="plain" type="success">自定义</el-tag>
              <el-tag effect="plain">无模板</el-tag>
            </div>
            <el-button type="primary" @click.stop="createBlankAgent">从空白创建</el-button>
          </article>
          <article v-for="template in templates" :key="template.id" class="template-card">
            <h3>{{ template.name }}</h3>
            <p>{{ template.persona || template.default_config?.persona || '快速创建一个面向业务任务的 AI 助手。' }}</p>
            <div class="tag-row">
              <el-tag effect="plain">{{ template.type }}</el-tag>
              <el-tag effect="plain">模板</el-tag>
            </div>
            <el-button type="primary" @click="selectTemplate(template)">选择模板</el-button>
          </article>
        </div>

        <el-form label-position="top">
          <template v-if="activeStep === 1">
          <el-form-item label="智能体名称">
            <el-input v-model="form.name" />
            <div class="field-help">名称用于区分不同智能体，在当前企业内不能重复。</div>
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="form.type">
              <el-option label="知识问答" value="qa" />
              <el-option label="智能问数" value="nl2data" />
            </el-select>
          </el-form-item>
          <el-form-item label="模板">
            <el-select v-model="form.template_id" clearable>
              <el-option v-for="template in templates" :key="template.id" :label="template.name" :value="template.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="一句话描述">
            <el-input placeholder="例如：帮助业务人员查询制度、流程和合同审批要点" />
          </el-form-item>
          </template>
          <template v-if="activeStep === 2">
          <el-form-item label="模型">
            <el-select v-model="form.model_id" clearable>
              <el-option v-for="model in models" :key="model.id" :label="model.name" :value="model.id" />
            </el-select>
            <div class="field-help">请选择模型中心中已经完成模型接入的模型。</div>
          </el-form-item>
          <el-form-item label="知识库">
            <el-select v-model="form.kb_ids" multiple clearable collapse-tags collapse-tags-tooltip placeholder="选择要挂载的知识库">
              <el-option
                v-for="kb in activeKbs"
                :key="kb.id"
                :label="`${kb.name} · ${kb.type}`"
                :value="kb.id"
              />
            </el-select>
            <div class="field-help">可选择一个或多个企业专属资料库，作为智能体回答问题的依据。</div>
          </el-form-item>
          <el-collapse>
            <el-collapse-item title="基础召回参数" name="rag">
              <div class="grid two">
                <el-form-item label="召回数量">
                  <el-input-number v-model="form.rag.top_k" :min="1" :max="20" />
                </el-form-item>
                <el-form-item label="相似度阈值">
                  <el-input-number v-model="form.rag.score_threshold" :min="0" :max="1" :step="0.05" />
                </el-form-item>
              </div>
              <el-form-item label="检索模式">
                <el-segmented v-model="form.rag.match_type" :options="[
                  { label: '混合', value: 'hybrid' },
                  { label: '向量', value: 'vector' },
                  { label: '关键词', value: 'keyword' },
                ]" />
              </el-form-item>
            </el-collapse-item>
          </el-collapse>
          <el-form-item label="角色设定">
            <el-input v-model="form.persona" type="textarea" :rows="4" />
          </el-form-item>
          <el-form-item label="结构化回答">
            <el-switch
              v-model="form.answer_style_enabled"
              active-text="开启"
              inactive-text="关闭"
            />
            <div class="field-help">开启后，智能体会优先采用结论先行、表格对比、步骤编号等清晰的回答方式。</div>
          </el-form-item>
          <el-alert title="创建后可先在对话中验证效果，确认无误后再发布给业务人员使用。" type="info" :closable="false" />
          </template>
          <template v-if="activeStep === 3">
            <el-result icon="success" title="智能体已创建" sub-title="下一步进入对话验证，检查回答内容、知识库命中测试和引用质量。">
              <template #extra>
                <el-button type="primary" @click="router.push(`/chat?agent_id=${createdAgentId}`)">立即测试</el-button>
                <el-button @click="router.push('/kbs')">配置知识库</el-button>
                <el-button @click="router.push('/publish')">发布</el-button>
              </template>
            </el-result>
          </template>
          <div v-if="activeStep < 3" class="form-actions mt">
            <el-button :disabled="activeStep === 0" @click="activeStep--">上一步</el-button>
            <el-button v-if="activeStep < 2" type="primary" @click="activeStep++">下一步</el-button>
            <el-button v-else type="primary" :loading="creating" @click="createAgent">创建并验证</el-button>
          </div>
        </el-form>
      </section>

    <el-dialog v-model="editVisible" title="编辑智能体能力" width="640px">
      <el-form label-position="top">
        <el-form-item label="智能体名称">
          <el-input v-model="editForm.name" />
          <div class="field-help">修改名称会同步影响列表展示。</div>
        </el-form-item>
        <el-form-item label="模型">
          <el-select v-model="editForm.model_id" clearable>
            <el-option v-for="model in models" :key="model.id" :label="model.name" :value="model.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="知识库">
          <el-select v-model="editForm.kb_ids" multiple clearable collapse-tags collapse-tags-tooltip placeholder="选择要挂载的知识库">
            <el-option
              v-for="kb in activeKbs"
              :key="kb.id"
              :label="`${kb.name} · ${kb.type}`"
              :value="kb.id"
            />
          </el-select>
          <div class="field-help">保存后，新的对话将使用更新后的知识库配置。</div>
        </el-form-item>
        <el-collapse>
          <el-collapse-item title="基础召回参数" name="rag">
            <div class="grid two">
              <el-form-item label="召回数量">
                <el-input-number v-model="editForm.rag.top_k" :min="1" :max="20" />
              </el-form-item>
              <el-form-item label="相似度阈值">
                <el-input-number v-model="editForm.rag.score_threshold" :min="0" :max="1" :step="0.05" />
              </el-form-item>
            </div>
            <el-form-item label="检索模式">
              <el-segmented v-model="editForm.rag.match_type" :options="[
                { label: '混合', value: 'hybrid' },
                { label: '向量', value: 'vector' },
                { label: '关键词', value: 'keyword' },
              ]" />
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
        <el-form-item label="角色设定">
          <el-input v-model="editForm.persona" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="结构化回答">
          <el-switch
            v-model="editForm.answer_style_enabled"
            active-text="开启"
            inactive-text="关闭"
          />
          <div class="field-help">关闭后，智能体将更多遵循原始角色设定回答。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="updating" @click="updateAgent">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.wizard-step-intro h3 {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-section-title);
  font-weight: 600;
}

.wizard-step-intro p {
  margin: var(--space-1) 0 0;
  color: var(--color-text-tertiary);
}

.blank-template-card {
  border-color: rgba(37, 99, 235, 0.28);
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.08), rgba(255, 255, 255, 0.96));
  cursor: pointer;
}

.blank-template-card:hover {
  border-color: rgba(37, 99, 235, 0.48);
  box-shadow: var(--shadow-card-hover);
}

.blank-template-card:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.24);
  outline-offset: 2px;
}
</style>
