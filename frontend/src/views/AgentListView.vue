<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { apiFetch } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'
import type { Agent, AgentRagConfig, AgentTemplate, KnowledgeBase, Model } from '../api/types'

const agents = ref<Agent[]>([])
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
      apiFetch<Agent[]>('/agents'),
      apiFetch<AgentTemplate[]>('/agent-templates'),
      apiFetch<Model[]>('/models'),
      apiFetch<KnowledgeBase[]>('/kbs'),
    ])
    agents.value = agentRows
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
    await apiFetch<Agent>('/agents', {
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
    ElMessage.success('智能体已创建')
    await loadData()
    activeStep.value = 3
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

function goTemplateGallery() {
  router.push('/templates')
}

async function publishAgent(agent: Agent) {
  try {
    await apiFetch<Agent>(`/agents/${agent.id}/publish`, { method: 'POST', body: {} })
    ElMessage.success('智能体已发布')
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
    await apiFetch<Agent>(`/agents/${editingAgent.value.id}`, {
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
  const message = error instanceof Error ? error.message : String(error || '请求失败')
  const map: Record<string, string> = {
    agent_name_exists: '智能体名称已存在，请换一个名称后重试。',
    model_not_found: '模型不存在，请重新选择模型。',
    agent_template_not_found: '模板不存在，请重新选择模板。',
    agent_template_type_mismatch: '模板类型和智能体类型不一致，请重新选择模板。',
  }
  return map[message] || message
}

onMounted(loadData)
</script>

<template>
  <section class="business-page">
    <PageHeader title="智能体工厂" description="围绕“选模板、填信息、配能力、进调试”的路径创建业务助手。">
      <template #actions>
        <el-button @click="goTemplateGallery">模板广场</el-button>
        <el-button type="primary" @click="activeTab = 'create'">创建智能体</el-button>
      </template>
    </PageHeader>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="智能体列表" name="list" />
      <el-tab-pane label="创建向导" name="create" />
    </el-tabs>

    <section v-if="activeTab === 'list'" class="panel-card">
        <SectionHeader title="智能体列表" description="查看、编辑和发布当前租户下的业务智能体。">
          <template #actions>
            <el-button @click="loadData">刷新</el-button>
          </template>
        </SectionHeader>
        <el-table v-loading="loading" :data="agents" border>
          <template #empty>
            <EmptyState title="还没有智能体" description="可以从模板开始创建第一个业务助手，并挂载模型、知识库和工具。" action-text="创建智能体" @action="activeTab = 'create'" />
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
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button v-if="row.status !== 'active'" size="small" @click="publishAgent(row)">发布</el-button>
              <StatusTag v-else status="active" label="可用" />
            </template>
          </el-table-column>
        </el-table>
      </section>

    <section v-else class="panel-card">
        <SectionHeader title="创建智能体" description="按步骤完成模板、基础信息和能力配置。" />
        <el-steps :active="activeStep" finish-status="success" simple>
          <el-step title="选择模板" />
          <el-step title="基础信息" />
          <el-step title="能力配置" />
          <el-step title="进入调试" />
        </el-steps>

        <div v-if="activeStep === 0" class="template-grid mt">
          <article v-for="template in templates" :key="template.id" class="template-card">
            <h3>{{ template.name }}</h3>
            <p>{{ template.persona || template.default_config?.persona || '快速创建一个业务智能体。' }}</p>
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
            <div class="field-help">名称在当前租户内不能重复。</div>
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
            <div class="field-help">模型来自模型中心的已接入模型。</div>
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
            <div class="field-help">可多选，运行时会按召回参数注入上下文。</div>
          </el-form-item>
          <el-collapse>
            <el-collapse-item title="基础召回参数" name="rag">
              <div class="grid two">
                <el-form-item label="TopK">
                  <el-input-number v-model="form.rag.top_k" :min="1" :max="20" />
                </el-form-item>
                <el-form-item label="Score Threshold">
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
          <el-form-item label="人设">
            <el-input v-model="form.persona" type="textarea" :rows="4" />
          </el-form-item>
          <el-form-item label="结构化回答">
            <el-switch
              v-model="form.answer_style_enabled"
              active-text="开启"
              inactive-text="关闭"
            />
            <div class="field-help">开启后平台会注入统一回答规范：结论先行、表格对比、步骤编号、命令配置用代码块。</div>
          </el-form-item>
          <el-alert title="当前创建的是草稿配置，完成后会直接进入调试，不影响线上版本。" type="info" :closable="false" />
          </template>
          <template v-if="activeStep === 3">
            <el-result icon="success" title="智能体已创建" sub-title="下一步进入调试对话，验证提示词、知识库和引用质量。">
              <template #extra>
                <el-button type="primary" @click="router.push('/chat')">进入调试</el-button>
              </template>
            </el-result>
          </template>
          <div v-if="activeStep < 3" class="form-actions mt">
            <el-button :disabled="activeStep === 0" @click="activeStep--">上一步</el-button>
            <el-button v-if="activeStep < 2" type="primary" @click="activeStep++">下一步</el-button>
            <el-button v-else type="primary" :loading="creating" @click="createAgent">创建并调试</el-button>
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
          <div class="field-help">保存后新对话会使用更新后的知识库绑定。</div>
        </el-form-item>
        <el-collapse>
          <el-collapse-item title="基础召回参数" name="rag">
            <div class="grid two">
              <el-form-item label="TopK">
                <el-input-number v-model="editForm.rag.top_k" :min="1" :max="20" />
              </el-form-item>
              <el-form-item label="Score Threshold">
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
        <el-form-item label="人设">
          <el-input v-model="editForm.persona" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="结构化回答">
          <el-switch
            v-model="editForm.answer_style_enabled"
            active-text="开启"
            inactive-text="关闭"
          />
          <div class="field-help">关闭后系统提示词不再追加平台统一回答风格规范。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="updating" @click="updateAgent">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>
