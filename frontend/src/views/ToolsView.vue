<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, Code2, Hammer, Network, PlugZap, Wrench } from 'lucide-vue-next'

import { apiFetch } from '../api/client'
import type { Agent, Tool } from '../api/types'
import EmptyState from '../components/common/EmptyState.vue'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'

type ToolCategory = 'capability' | 'ops'
type ToolType = 'http' | 'code' | 'builtin' | 'mcp'

interface SchemaField {
  name: string
  type: string
  required: boolean
  description: string
}

interface ToolForm {
  name: string
  type: ToolType
  summary: string
  category: ToolCategory
  group: string
  audience: 'agent' | 'admin'
  availability: 'available' | 'coming_soon'
  schemaFields: SchemaField[]
  http: {
    url: string
    method: string
  }
  headers: Array<{ key: string; value: string }>
  code: string
  builtin: string
  mcp: {
    name: string
    transport: 'sse' | 'http'
    server_url: string
    auth_type: 'none' | 'header' | 'bearer'
    auth_header: string
    auth_token: string
  }
}

interface ToolDraft {
  name: string
  type: ToolType
  summary: string
  tool_schema?: Record<string, unknown>
  schema?: Record<string, unknown>
  config?: Record<string, unknown>
}

const tools = ref<Tool[]>([])
const agents = ref<Agent[]>([])
const loading = ref(false)
const saving = ref(false)
const running = ref(false)
const binding = ref(false)
const drafting = ref(false)
const activeCategory = ref<ToolCategory>('capability')
const detailVisible = ref(false)
const createVisible = ref(false)
const draftVisible = ref(false)
const createStep = ref(0)
const selectedTool = ref<Tool | null>(null)
const runInput = ref<Record<string, unknown>>({})
const runResult = ref<Record<string, unknown> | null>(null)
const bindAgentIds = ref<string[]>([])
const draftForm = reactive({
  description: '',
  endpoint: '',
  method: 'GET',
  auth: '',
})
const form = reactive<ToolForm>(emptyToolForm())

const filteredTools = computed(() => tools.value.filter((tool) => toolCategory(tool) === activeCategory.value))
const selectedSchemaFields = computed(() => schemaFields(selectedTool.value))
const selectedConfig = computed(() => selectedTool.value?.config || {})
const selectedAvailability = computed(() => availabilityLabel(String(selectedConfig.value.availability || 'available')))
const canRunSelectedTool = computed(() => selectedTool.value && selectedConfig.value.availability !== 'coming_soon')
const selectedToolRunFields = computed(() => selectedSchemaFields.value)

async function loadData() {
  loading.value = true
  try {
    const [toolRows, agentRows] = await Promise.all([apiFetch<Tool[]>('/tools'), apiFetch<Agent[]>('/agents')])
    tools.value = toolRows
    agents.value = agentRows.filter((agent) => agent.status !== 'archived')
  } finally {
    loading.value = false
  }
}

function openDetail(tool: Tool) {
  selectedTool.value = tool
  runInput.value = defaultRunInput(tool)
  runResult.value = null
  bindAgentIds.value = agents.value.filter((agent) => (agent.tool_ids || []).includes(tool.id)).map((agent) => agent.id)
  detailVisible.value = true
}

function openManualCreate() {
  resetForm()
  createStep.value = 0
  createVisible.value = true
}

function openDraftCreate() {
  draftForm.description = ''
  draftForm.endpoint = ''
  draftForm.method = 'GET'
  draftForm.auth = ''
  draftVisible.value = true
}

async function createDraft() {
  if (!draftForm.description.trim()) {
    ElMessage.warning('请先描述要构建的工具能力')
    return
  }
  drafting.value = true
  try {
    const draft = await apiFetch<ToolDraft>('/tools/draft', {
      method: 'POST',
      body: {
        description: draftForm.description,
        hint: {
          endpoint: draftForm.endpoint || undefined,
          method: draftForm.method || undefined,
          auth: draftForm.auth || undefined,
        },
      },
    })
    resetForm()
    applyDraftToForm(draft)
    draftVisible.value = false
    createStep.value = 1
    createVisible.value = true
    ElMessage.success('已生成工具草稿，请确认后保存')
  } catch (error) {
    ElMessage.error(formatError(error))
  } finally {
    drafting.value = false
  }
}

async function saveTool() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写工具名称')
    return
  }
  saving.value = true
  try {
    await apiFetch<Tool>('/tools', {
      method: 'POST',
      body: {
        name: form.name,
        type: form.type,
        schema: buildSchema(),
        config: buildConfig(),
      },
    })
    ElMessage.success('工具已创建')
    createVisible.value = false
    await loadData()
  } catch (error) {
    ElMessage.error(formatError(error))
  } finally {
    saving.value = false
  }
}

async function runSelectedTool() {
  if (!selectedTool.value) return
  if (!canRunSelectedTool.value) {
    ElMessage.info('该工具即将支持接入，当前暂不可试运行')
    return
  }
  running.value = true
  try {
    const result = await apiFetch<{ output: Record<string, unknown> }>(`/tools/${selectedTool.value.id}/run`, {
      method: 'POST',
      body: { input: runInput.value },
    })
    runResult.value = result.output
  } catch (error) {
    ElMessage.error(formatError(error))
  } finally {
    running.value = false
  }
}

async function bindSelectedTool() {
  if (!selectedTool.value) return
  binding.value = true
  try {
    await apiFetch(`/tools/${selectedTool.value.id}/bind`, {
      method: 'POST',
      body: { agent_ids: bindAgentIds.value },
    })
    ElMessage.success('绑定关系已保存')
    await loadData()
  } catch (error) {
    ElMessage.error(formatError(error))
  } finally {
    binding.value = false
  }
}

function addSchemaField() {
  form.schemaFields.push({ name: '', type: 'string', required: false, description: '' })
}

function removeSchemaField(index: number) {
  form.schemaFields.splice(index, 1)
}

function addHeader() {
  form.headers.push({ key: '', value: '' })
}

function removeHeader(index: number) {
  form.headers.splice(index, 1)
}

function resetForm() {
  Object.assign(form, emptyToolForm())
}

function emptyToolForm(): ToolForm {
  return {
    name: '',
    type: 'http',
    summary: '',
    category: 'capability',
    group: 'http',
    audience: 'agent',
    availability: 'available',
    schemaFields: [{ name: 'query', type: 'string', required: true, description: '需要工具处理的问题或参数。' }],
    http: {
      url: '',
      method: 'GET',
    },
    headers: [],
    code: '',
    builtin: 'echo',
    mcp: {
      name: '',
      transport: 'sse',
      server_url: '',
      auth_type: 'none',
      auth_header: '',
      auth_token: '',
    },
  }
}

function applyDraftToForm(draft: ToolDraft) {
  form.name = draft.name || '新建工具草稿'
  form.type = normalizeToolType(draft.type)
  form.summary = draft.summary || ''
  form.schemaFields = schemaFields({ id: 'draft', status: 'draft', ...draft, tool_schema: draft.tool_schema || draft.schema } as Tool)
  const config = draft.config || {}
  form.category = config.category === 'ops' ? 'ops' : 'capability'
  form.group = String(config.group || form.type)
  form.audience = config.audience === 'admin' ? 'admin' : 'agent'
  form.availability = config.availability === 'coming_soon' ? 'coming_soon' : 'available'
  if (form.type === 'http') {
    form.http.url = String(config.url || '')
    form.http.method = String(config.method || 'GET').toUpperCase()
    form.headers = objectToPairs(config.headers)
  }
  if (form.type === 'code') {
    form.code = String(config.code || '')
  }
  if (form.type === 'builtin') {
    form.builtin = String(config.builtin || 'echo')
  }
  if (form.type === 'mcp') {
    const mcp = typeof config.mcp === 'object' && config.mcp !== null ? (config.mcp as Record<string, unknown>) : {}
    const auth = typeof mcp.auth === 'object' && mcp.auth !== null ? (mcp.auth as Record<string, unknown>) : {}
    form.mcp.name = String(mcp.name || form.name)
    form.mcp.transport = mcp.transport === 'http' ? 'http' : 'sse'
    form.mcp.server_url = String(mcp.server_url || '')
    form.mcp.auth_type = auth.type === 'header' || auth.type === 'bearer' ? auth.type : 'none'
    form.mcp.auth_header = String(auth.header || '')
    form.mcp.auth_token = String(auth.token || '')
    form.availability = 'coming_soon'
  }
}

function buildSchema() {
  const properties: Record<string, unknown> = {}
  const required: string[] = []
  for (const field of form.schemaFields) {
    const name = field.name.trim()
    if (!name) continue
    properties[name] = {
      type: field.type,
      description: field.description,
    }
    if (field.required) required.push(name)
  }
  return {
    type: 'object',
    properties,
    required,
  }
}

function buildConfig() {
  const config: Record<string, unknown> = {
    category: form.category,
    group: form.group || form.type,
    audience: form.audience,
    availability: form.type === 'mcp' ? 'coming_soon' : form.availability,
    summary: form.summary,
  }
  if (form.type === 'http') {
    config.url = form.http.url
    config.method = form.http.method
    config.headers = pairsToObject(form.headers)
  }
  if (form.type === 'code') {
    config.code = form.code
  }
  if (form.type === 'builtin') {
    config.builtin = form.builtin
  }
  if (form.type === 'mcp') {
    config.mcp = {
      name: form.mcp.name || form.name,
      transport: form.mcp.transport,
      server_url: form.mcp.server_url,
      auth: {
        type: form.mcp.auth_type,
        header: form.mcp.auth_header || undefined,
        token: form.mcp.auth_token || undefined,
      },
    }
  }
  return config
}

function toolCategory(tool: Tool): ToolCategory {
  return tool.config?.category === 'ops' ? 'ops' : 'capability'
}

function toolSummary(tool: Tool) {
  const config = tool.config || {}
  return String(config.summary || config.description || '用于扩展智能体或平台管理流程的工具能力。')
}

function toolUsage(tool: Tool) {
  const config = tool.config || {}
  if (config.usage) return String(config.usage)
  if (tool.type === 'http') return '填写参数后调用外部服务，返回结果可供智能体或管理员参考。'
  if (tool.type === 'code') return '通过受控代码执行处理输入数据，适合数据转换、计算和格式整理。'
  if (tool.type === 'builtin') return '使用平台内置能力完成固定任务，适合稳定的标准化操作。'
  if (tool.type === 'mcp') return '配置外部 MCP Server 后，后续可作为智能体能力插件接入。'
  return '按参数说明填写输入后即可试运行。'
}

function schemaFields(tool: Tool | null): SchemaField[] {
  const schema = (tool?.tool_schema || tool?.schema || {}) as Record<string, unknown>
  const properties = typeof schema.properties === 'object' && schema.properties !== null ? (schema.properties as Record<string, unknown>) : {}
  const required = Array.isArray(schema.required) ? schema.required.map(String) : []
  const fields = Object.entries(properties).map(([name, value]) => {
    const item = typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {}
    return {
      name,
      type: String(item.type || 'string'),
      required: required.includes(name),
      description: String(item.description || '请按业务需要填写。'),
    }
  })
  return fields.length > 0 ? fields : [{ name: 'query', type: 'string', required: true, description: '需要工具处理的问题或参数。' }]
}

function defaultRunInput(tool: Tool) {
  const input: Record<string, unknown> = {}
  for (const field of schemaFields(tool)) {
    input[field.name] = field.type === 'number' || field.type === 'integer' ? 0 : ''
  }
  return input
}

function normalizeToolType(type: string): ToolType {
  return ['http', 'code', 'builtin', 'mcp'].includes(type) ? (type as ToolType) : 'http'
}

function typeLabel(type: string) {
  const labels: Record<string, string> = {
    http: 'HTTP',
    code: '代码',
    builtin: '内置',
    mcp: 'MCP',
  }
  return labels[type] || type
}

function groupLabel(group: unknown) {
  const labels: Record<string, string> = {
    http: '外部接口',
    code: '代码执行',
    builtin: '平台内置',
    mcp: 'MCP 服务',
    search: '检索查询',
    data: '数据处理',
    ops: '运维管理',
  }
  const key = String(group || '')
  return labels[key] || key || '通用能力'
}

function audienceLabel(audience: unknown) {
  return audience === 'admin' ? '供管理员使用' : '供智能体调用'
}

function availabilityLabel(value: string) {
  return value === 'coming_soon' ? '即将支持接入' : '可用'
}

function statusType(tool: Tool) {
  if (tool.config?.availability === 'coming_soon') return 'info'
  if (tool.status === 'active') return 'success'
  if (tool.status === 'disabled') return 'warning'
  return 'info'
}

function iconForTool(tool: Tool) {
  if (tool.type === 'http') return PlugZap
  if (tool.type === 'code') return Code2
  if (tool.type === 'builtin') return Hammer
  if (tool.type === 'mcp') return Network
  return Wrench
}

function objectToPairs(value: unknown) {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => ({ key, value: String(item ?? '') }))
}

function pairsToObject(pairs: Array<{ key: string; value: string }>) {
  return pairs.reduce<Record<string, string>>((result, item) => {
    if (item.key.trim()) result[item.key.trim()] = item.value
    return result
  }, {})
}

function resultEntries(value: Record<string, unknown> | null) {
  return Object.entries(value || {}).map(([key, item]) => ({ key, value: formatValue(item) }))
}

function formatValue(value: unknown) {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return `数组（${value.length} 项）`
  if (typeof value === 'object') return `对象（${Object.keys(value as Record<string, unknown>).length} 项）`
  return String(value)
}

function formatError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || '请求失败')
  const map: Record<string, string> = {
    tool_name_exists: '工具名称已存在，请换一个名称后重试。',
    tool_not_found: '工具不存在或已被删除。',
    no_active_model_channel: '请先在模型中心接入并启用对话模型，再使用对话式构建。',
  }
  return map[message] || message
}

onMounted(loadData)
</script>

<template>
  <section class="tools-page">
    <PageHeader title="工具中心" description="集中管理智能体可调用的能力插件，以及平台运维使用的实用工具。">
      <template #actions>
        <el-button @click="loadData">刷新</el-button>
        <el-dropdown trigger="click" @command="(command: string) => command === 'draft' ? openDraftCreate() : openManualCreate()">
          <el-button type="primary">
            新建工具
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="manual">手动新建</el-dropdown-item>
              <el-dropdown-item command="draft">对话式构建</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </template>
    </PageHeader>

    <section class="panel-card tools-toolbar">
      <el-radio-group v-model="activeCategory">
        <el-radio-button label="capability">能力插件</el-radio-button>
        <el-radio-button label="ops">运维工具</el-radio-button>
      </el-radio-group>
      <span>{{ activeCategory === 'capability' ? '供智能体调用，扩展业务处理能力。' : '供管理员使用，辅助平台运维管理。' }}</span>
    </section>

    <section v-loading="loading" class="tool-gallery">
      <article v-for="tool in filteredTools" :key="tool.id" class="panel-card tool-card">
        <div class="tool-card__head">
          <div class="tool-icon">
            <component :is="iconForTool(tool)" :size="22" />
          </div>
          <div>
            <h2>{{ tool.name }}</h2>
            <div class="tool-tags">
              <el-tag size="small">{{ groupLabel(tool.config?.group || tool.type) }}</el-tag>
              <el-tag size="small" :type="tool.config?.audience === 'admin' ? 'warning' : 'success'">
                {{ audienceLabel(tool.config?.audience) }}
              </el-tag>
            </div>
          </div>
        </div>
        <p>{{ toolSummary(tool) }}</p>
        <div class="tool-card__meta">
          <StatusTag :status="tool.status || 'active'" />
          <el-tag size="small" :type="statusType(tool)">
            {{ selectedTool?.id === tool.id ? selectedAvailability : availabilityLabel(String(tool.config?.availability || 'available')) }}
          </el-tag>
          <el-tag size="small" type="info">{{ typeLabel(tool.type) }}</el-tag>
        </div>
        <div class="tool-card__actions">
          <el-button @click="openDetail(tool)">详情</el-button>
          <el-button :disabled="tool.config?.availability === 'coming_soon'" @click="openDetail(tool)">试运行</el-button>
          <el-button v-if="toolCategory(tool) === 'capability'" type="primary" plain @click="openDetail(tool)">绑定</el-button>
        </div>
      </article>
      <EmptyState
        v-if="!loading && filteredTools.length === 0"
        class="panel-card tool-empty"
        title="还没有工具"
        description="请通过手动新建或对话式构建创建第一个工具，并按用途归入能力插件或运维工具。"
        action-text="新建工具"
        @action="openManualCreate"
      />
    </section>

    <el-drawer v-model="detailVisible" size="58%" :title="selectedTool?.name || '工具详情'">
      <div v-if="selectedTool" class="drawer-stack">
        <section class="detail-overview">
          <article>
            <strong>是什么</strong>
            <p>{{ toolSummary(selectedTool) }}</p>
          </article>
          <article>
            <strong>给谁用</strong>
            <p>{{ audienceLabel(selectedTool.config?.audience) }}</p>
          </article>
          <article>
            <strong>怎么用</strong>
            <p>{{ toolUsage(selectedTool) }}</p>
          </article>
        </section>

        <section class="panel-card drawer-panel">
          <SectionHeader title="参数说明" description="按字段填写输入，智能体或管理员将按这些参数调用工具。" />
          <el-table :data="selectedSchemaFields" border>
            <el-table-column prop="name" label="字段名" min-width="140" />
            <el-table-column prop="type" label="类型" width="120" />
            <el-table-column label="必填" width="90">
              <template #default="{ row }">{{ row.required ? '是' : '否' }}</template>
            </el-table-column>
            <el-table-column prop="description" label="说明" min-width="220" />
          </el-table>
        </section>

        <section class="panel-card drawer-panel">
          <SectionHeader title="在线试运行" description="按参数说明填写一次输入，检查工具返回结果。">
            <template #actions>
              <el-tag v-if="selectedTool.config?.availability === 'coming_soon'" type="info">即将支持</el-tag>
            </template>
          </SectionHeader>
          <el-alert
            v-if="selectedTool.config?.availability === 'coming_soon'"
            title="该类型工具当前可配置、可保存、可展示，外部执行能力即将支持。"
            type="info"
            :closable="false"
          />
          <el-form v-else label-position="top">
            <el-form-item v-for="field in selectedToolRunFields" :key="field.name" :label="field.name">
              <el-input-number
                v-if="field.type === 'number' || field.type === 'integer'"
                v-model="runInput[field.name]"
                :precision="field.type === 'integer' ? 0 : 2"
              />
              <el-input v-else v-model="runInput[field.name]" :placeholder="field.description" />
            </el-form-item>
            <el-button type="primary" :loading="running" @click="runSelectedTool">开始试运行</el-button>
          </el-form>
          <div v-if="runResult" class="run-result">
            <h3>运行结果</h3>
            <el-table :data="resultEntries(runResult)" border>
              <el-table-column prop="key" label="字段" width="180" />
              <el-table-column prop="value" label="结果" min-width="260" show-overflow-tooltip />
            </el-table>
            <el-collapse class="mt">
              <el-collapse-item title="原始数据（开发者）" name="raw-data">
                <pre>{{ JSON.stringify(runResult, null, 2) }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </section>

        <section v-if="toolCategory(selectedTool) === 'capability'" class="panel-card drawer-panel">
          <SectionHeader title="绑定智能体" description="选择可调用该工具的智能体，保存后会同步更新绑定关系。" />
          <el-select v-model="bindAgentIds" multiple clearable filterable collapse-tags collapse-tags-tooltip placeholder="选择智能体">
            <el-option v-for="agent in agents" :key="agent.id" :label="agent.name" :value="agent.id" />
          </el-select>
          <div class="drawer-actions">
            <el-button type="primary" :loading="binding" @click="bindSelectedTool">保存绑定</el-button>
          </div>
        </section>

        <section class="panel-card drawer-panel">
          <SectionHeader title="配置" description="查看当前工具的连接方式与执行设置。" />
          <el-descriptions :column="1" border>
            <el-descriptions-item label="类型">{{ typeLabel(selectedTool.type) }}</el-descriptions-item>
            <el-descriptions-item label="分类">{{ groupLabel(selectedTool.config?.group || selectedTool.type) }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ availabilityLabel(String(selectedTool.config?.availability || 'available')) }}</el-descriptions-item>
            <el-descriptions-item v-if="selectedTool.type === 'http'" label="接口地址">{{ selectedTool.config?.url || '-' }}</el-descriptions-item>
            <el-descriptions-item v-if="selectedTool.type === 'http'" label="请求方式">{{ selectedTool.config?.method || 'GET' }}</el-descriptions-item>
            <el-descriptions-item v-if="selectedTool.type === 'builtin'" label="内置能力">{{ selectedTool.config?.builtin || selectedTool.name }}</el-descriptions-item>
            <el-descriptions-item v-if="selectedTool.type === 'mcp'" label="服务地址">
              {{ ((selectedTool.config?.mcp as Record<string, unknown> | undefined)?.server_url) || '-' }}
            </el-descriptions-item>
          </el-descriptions>
        </section>
      </div>
    </el-drawer>

    <el-drawer v-model="createVisible" size="62%" title="新建工具">
      <div class="drawer-stack">
        <el-steps :active="createStep" finish-status="success" simple>
          <el-step title="选择类型" />
          <el-step title="基础信息" />
          <el-step title="参数与配置" />
        </el-steps>

        <section v-if="createStep === 0" class="create-type-grid">
          <button v-for="item in ['http', 'code', 'builtin', 'mcp']" :key="item" class="type-card" :class="{ active: form.type === item }" @click="form.type = item as ToolType">
            <component :is="iconForTool({ type: item } as Tool)" :size="24" />
            <strong>{{ typeLabel(item) }}</strong>
            <span>{{ item === 'mcp' ? '配置外部 MCP Server，本期保存展示，执行即将支持。' : '配置后可保存并在线试运行。' }}</span>
          </button>
        </section>

        <section v-if="createStep === 1" class="panel-card drawer-panel">
          <SectionHeader title="基础信息" description="说明工具是什么、归属哪类能力，以及主要面向谁使用。" />
          <el-form label-position="top">
            <el-form-item label="工具名称">
              <el-input v-model="form.name" placeholder="例如：工单查询助手" />
            </el-form-item>
            <el-form-item label="一句话说明">
              <el-input v-model="form.summary" type="textarea" :rows="3" placeholder="说明这个工具能完成什么任务。" />
            </el-form-item>
            <div class="form-grid">
              <el-form-item label="大类">
                <el-select v-model="form.category">
                  <el-option label="能力插件" value="capability" />
                  <el-option label="运维工具" value="ops" />
                </el-select>
              </el-form-item>
              <el-form-item label="分类">
                <el-select v-model="form.group" allow-create filterable default-first-option>
                  <el-option label="外部接口" value="http" />
                  <el-option label="代码执行" value="code" />
                  <el-option label="平台内置" value="builtin" />
                  <el-option label="MCP 服务" value="mcp" />
                  <el-option label="数据处理" value="data" />
                  <el-option label="运维管理" value="ops" />
                </el-select>
              </el-form-item>
              <el-form-item label="使用对象">
                <el-select v-model="form.audience">
                  <el-option label="供智能体调用" value="agent" />
                  <el-option label="供管理员使用" value="admin" />
                </el-select>
              </el-form-item>
              <el-form-item label="可用状态">
                <el-select v-model="form.availability" :disabled="form.type === 'mcp'">
                  <el-option label="可用" value="available" />
                  <el-option label="即将支持接入" value="coming_soon" />
                </el-select>
              </el-form-item>
            </div>
          </el-form>
        </section>

        <section v-if="createStep === 2" class="panel-card drawer-panel">
          <SectionHeader title="参数与配置" description="定义工具需要哪些输入，并填写对应类型的连接或执行配置。" />
          <div class="schema-editor">
            <div class="schema-editor__head">
              <strong>输入参数</strong>
              <el-button size="small" @click="addSchemaField">新增字段</el-button>
            </div>
            <div v-for="(field, index) in form.schemaFields" :key="index" class="schema-row">
              <el-input v-model="field.name" placeholder="字段名" />
              <el-select v-model="field.type">
                <el-option label="文本" value="string" />
                <el-option label="数字" value="number" />
                <el-option label="整数" value="integer" />
                <el-option label="布尔" value="boolean" />
                <el-option label="对象" value="object" />
                <el-option label="数组" value="array" />
              </el-select>
              <el-checkbox v-model="field.required">必填</el-checkbox>
              <el-input v-model="field.description" placeholder="说明" />
              <el-button text type="danger" @click="removeSchemaField(index)">删除</el-button>
            </div>
          </div>

          <div class="config-editor">
            <template v-if="form.type === 'http'">
              <div class="form-grid">
                <el-form-item label="接口地址">
                  <el-input v-model="form.http.url" placeholder="https://api.example.com/search" />
                </el-form-item>
                <el-form-item label="请求方式">
                  <el-select v-model="form.http.method">
                    <el-option label="GET" value="GET" />
                    <el-option label="POST" value="POST" />
                    <el-option label="PUT" value="PUT" />
                    <el-option label="PATCH" value="PATCH" />
                  </el-select>
                </el-form-item>
              </div>
              <div class="schema-editor__head">
                <strong>请求头</strong>
                <el-button size="small" @click="addHeader">新增请求头</el-button>
              </div>
              <div v-for="(header, index) in form.headers" :key="index" class="header-row">
                <el-input v-model="header.key" placeholder="名称" />
                <el-input v-model="header.value" placeholder="值" />
                <el-button text type="danger" @click="removeHeader(index)">删除</el-button>
              </div>
            </template>

            <template v-if="form.type === 'code'">
              <el-form-item label="执行代码">
                <el-input v-model="form.code" type="textarea" :rows="10" placeholder="输入受控执行代码。" />
              </el-form-item>
            </template>

            <template v-if="form.type === 'builtin'">
              <el-form-item label="内置能力">
                <el-select v-model="form.builtin" allow-create filterable>
                  <el-option label="回显" value="echo" />
                  <el-option label="计算器" value="calculator" />
                  <el-option label="智能问数" value="nl2data" />
                </el-select>
              </el-form-item>
            </template>

            <template v-if="form.type === 'mcp'">
              <el-alert title="MCP 工具本期支持配置、保存与展示，外部发现和调用执行即将支持。" type="info" :closable="false" />
              <div class="form-grid mt">
                <el-form-item label="MCP 名称">
                  <el-input v-model="form.mcp.name" placeholder="例如：企业知识 MCP" />
                </el-form-item>
                <el-form-item label="传输方式">
                  <el-select v-model="form.mcp.transport">
                    <el-option label="SSE" value="sse" />
                    <el-option label="HTTP" value="http" />
                  </el-select>
                </el-form-item>
                <el-form-item label="服务地址">
                  <el-input v-model="form.mcp.server_url" placeholder="https://mcp.example.com/sse" />
                </el-form-item>
                <el-form-item label="认证方式">
                  <el-select v-model="form.mcp.auth_type">
                    <el-option label="无认证" value="none" />
                    <el-option label="Header" value="header" />
                    <el-option label="Bearer Token" value="bearer" />
                  </el-select>
                </el-form-item>
                <el-form-item v-if="form.mcp.auth_type === 'header'" label="Header 名称">
                  <el-input v-model="form.mcp.auth_header" placeholder="X-API-Key" />
                </el-form-item>
                <el-form-item v-if="form.mcp.auth_type !== 'none'" label="认证值">
                  <el-input v-model="form.mcp.auth_token" type="password" show-password />
                </el-form-item>
              </div>
            </template>
          </div>
        </section>

        <div class="drawer-actions">
          <el-button :disabled="createStep === 0" @click="createStep -= 1">上一步</el-button>
          <el-button v-if="createStep < 2" type="primary" @click="createStep += 1">下一步</el-button>
          <el-button v-else type="primary" :loading="saving" @click="saveTool">保存工具</el-button>
        </div>
      </div>
    </el-drawer>

    <el-drawer v-model="draftVisible" size="42%" title="对话式构建工具">
      <section class="drawer-stack">
        <SectionHeader title="描述工具需求" description="用自然语言说明要连接的服务、要输入的参数，以及期望返回什么结果。" />
        <el-form label-position="top">
          <el-form-item label="需求描述">
            <el-input
              v-model="draftForm.description"
              type="textarea"
              :rows="6"
              placeholder="例如：我需要一个天气查询工具，输入城市名后调用外部接口返回天气、温度和提醒。"
            />
          </el-form-item>
          <el-form-item label="接口或服务地址">
            <el-input v-model="draftForm.endpoint" placeholder="可选，填写 HTTP 接口或 MCP Server 地址。" />
          </el-form-item>
          <div class="form-grid">
            <el-form-item label="请求方式">
              <el-select v-model="draftForm.method">
                <el-option label="GET" value="GET" />
                <el-option label="POST" value="POST" />
              </el-select>
            </el-form-item>
            <el-form-item label="认证说明">
              <el-input v-model="draftForm.auth" placeholder="可选，例如 Bearer Token 或 Header Key。" />
            </el-form-item>
          </div>
        </el-form>
        <div class="drawer-actions">
          <el-button @click="draftVisible = false">取消</el-button>
          <el-button type="primary" :loading="drafting" @click="createDraft">生成草稿</el-button>
        </div>
      </section>
    </el-drawer>
  </section>
</template>

<style scoped>
.tools-page {
  display: grid;
  gap: var(--space-5);
}

.tools-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}

.tools-toolbar span {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.tool-gallery {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}

.tool-card {
  display: grid;
  gap: var(--space-4);
}

.tool-card__head {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  align-items: center;
  gap: var(--space-3);
}

.tool-card h2 {
  margin: 0 0 var(--space-2);
  color: var(--color-text-primary);
  font-size: 18px;
}

.tool-card p {
  min-height: 48px;
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.tool-icon {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  border-radius: var(--radius-md);
  background: #eef4ff;
  color: #2563eb;
}

.tool-tags,
.tool-card__meta,
.tool-card__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.tool-card__actions {
  justify-content: flex-end;
}

.tool-empty {
  grid-column: 1 / -1;
}

.drawer-stack {
  display: grid;
  gap: var(--space-4);
}

.detail-overview {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}

.detail-overview article {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  background: #ffffff;
}

.detail-overview strong {
  color: var(--color-text-primary);
}

.detail-overview p {
  margin: var(--space-2) 0 0;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.drawer-panel {
  box-shadow: none;
}

.drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

.run-result {
  display: grid;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.run-result h3 {
  margin: 0;
  font-size: 16px;
}

.create-type-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
}

.type-card {
  display: grid;
  gap: var(--space-2);
  min-height: 150px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: #ffffff;
  padding: var(--space-4);
  color: var(--color-text-secondary);
  cursor: pointer;
  text-align: left;
}

.type-card.active {
  border-color: #2563eb;
  background: #eef4ff;
  color: #1d4ed8;
}

.type-card strong {
  color: var(--color-text-primary);
  font-size: 16px;
}

.type-card span {
  line-height: 1.5;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.schema-editor,
.config-editor {
  display: grid;
  gap: var(--space-3);
}

.config-editor {
  margin-top: var(--space-5);
}

.schema-editor__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.schema-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) 120px 80px minmax(180px, 1.4fr) 64px;
  align-items: center;
  gap: var(--space-2);
}

.header-row {
  display: grid;
  grid-template-columns: minmax(160px, 1fr) minmax(200px, 1.4fr) 64px;
  align-items: center;
  gap: var(--space-2);
}

pre {
  overflow: auto;
  max-height: 260px;
  margin: 0;
  border-radius: var(--radius-md);
  background: #0f172a;
  padding: var(--space-3);
  color: #e5e7eb;
}

@media (max-width: 1200px) {
  .tool-gallery,
  .create-type-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .detail-overview {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .tools-toolbar,
  .drawer-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .tool-gallery,
  .create-type-grid,
  .form-grid,
  .schema-row,
  .header-row {
    grid-template-columns: 1fr;
  }
}
</style>
