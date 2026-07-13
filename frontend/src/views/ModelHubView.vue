<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Edit, Link, Plus, Refresh } from '@element-plus/icons-vue'

import { apiFetch } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'
import type {
  ModelCatalog,
  ModelCenterChannelTestResponse,
  ModelCenterConnectRequest,
  ModelCenterConnectResponse,
  ModelChannel,
  ModelHub,
  ModelHubCreate,
  ModelHubUpdate,
} from '../api/types'

const models = ref<ModelHub[]>([])
const catalog = ref<ModelCatalog[]>([])
const channels = ref<ModelChannel[]>([])
const loading = ref(false)
const catalogLoading = ref(false)
const saving = ref(false)
const channelLoading = ref(false)
const connecting = ref(false)
const testingChannelId = ref('')
const createDialog = ref(false)
const editDialog = ref(false)
const channelDrawer = ref(false)
const connectDialog = ref(false)
const selectedModel = ref<ModelHub | null>(null)
const selectedCatalog = ref<ModelCatalog | null>(null)
const connectError = ref('')

const modelTypes = [
  { label: 'LLM', value: 'llm' },
  { label: 'Embedding', value: 'embedding' },
  { label: 'Rerank', value: 'rerank' },
]

const createForm = reactive({
  name: '',
  provider: '',
  type: 'llm',
  display_name: '',
  description: '',
  with_channel: true,
  base_url: '',
  api_key: '',
  weight: 1,
})

const editForm = reactive({
  display_name: '',
  description: '',
})

const catalogFilters = reactive({
  model_type: '',
  provider: '',
})

const connectForm = reactive({
  runtime_name: '',
  api_key: '',
  base_url: '',
  weight: 1,
})

const activeCount = computed(() => models.value.filter((model) => model.is_active !== false).length)
const catalogProviders = computed(() => Array.from(new Set(catalog.value.map((item) => item.provider))).sort())

function displayName(model: ModelHub) {
  return model.display_name || model.name
}

function resetCreateForm() {
  createForm.name = ''
  createForm.provider = ''
  createForm.type = 'llm'
  createForm.display_name = ''
  createForm.description = ''
  createForm.with_channel = true
  createForm.base_url = ''
  createForm.api_key = ''
  createForm.weight = 1
}

function friendlyError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  if (message.startsWith('connection_test_failed')) {
    const summary = message.includes(':') ? message.split(':').slice(1).join(':').trim() : ''
    return `连接测试失败，请检查 API Key 和地址${summary ? `（${summary}）` : ''}`
  }
  if (message === 'no_active_model_channel') return '请先在模型中心配置模型 API 并测试连通'
  if (message.startsWith('provider_http_')) return `供应商调用失败：${message}`
  if (message === 'model_name_exists') return '模型名已存在'
  if (message === 'model_channel_create_failed') return '默认渠道创建失败，请检查 MaaS 服务'
  if (message === 'protocol_not_supported') return '该协议暂不支持一键接入'
  if (message === 'model_type_not_supported') return '该模型类型暂不支持一键接入'
  return message
}

async function loadModels() {
  loading.value = true
  try {
    models.value = await apiFetch<ModelHub[]>('/model-hub/models?limit=100')
  } finally {
    loading.value = false
  }
}

async function loadCatalog() {
  catalogLoading.value = true
  try {
    const params = new URLSearchParams()
    if (catalogFilters.model_type) params.set('model_type', catalogFilters.model_type)
    if (catalogFilters.provider) params.set('provider', catalogFilters.provider)
    const query = params.toString()
    catalog.value = await apiFetch<ModelCatalog[]>(`/model-center/catalog${query ? `?${query}` : ''}`)
  } finally {
    catalogLoading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadModels(), loadCatalog()])
}

async function createModel() {
  if (!createForm.name.trim()) {
    ElMessage.warning('请填写模型名')
    return
  }
  if (createForm.with_channel && (!createForm.base_url.trim() || !createForm.api_key.trim())) {
    ElMessage.warning('请填写默认渠道地址和密钥')
    return
  }
  saving.value = true
  try {
    const body: ModelHubCreate = {
      name: createForm.name.trim(),
      provider: createForm.provider.trim() || null,
      type: createForm.type,
      display_name: createForm.display_name.trim() || null,
      description: createForm.description.trim() || null,
      default_channel: createForm.with_channel
        ? {
            base_url: createForm.base_url.trim(),
            api_key: createForm.api_key,
            weight: createForm.weight || 1,
            status: 'active',
          }
        : null,
    }
    await apiFetch<ModelHub>('/model-hub/models', { method: 'POST', body: { ...body } })
    createDialog.value = false
    resetCreateForm()
    await loadModels()
    ElMessage.success('模型已创建')
  } catch (error) {
    ElMessage.error(friendlyError(error))
  } finally {
    saving.value = false
  }
}

function openEdit(model: ModelHub) {
  selectedModel.value = model
  editForm.display_name = model.display_name || ''
  editForm.description = model.description || ''
  editDialog.value = true
}

async function updateModel() {
  if (!selectedModel.value) return
  saving.value = true
  try {
    const body: ModelHubUpdate = {
      display_name: editForm.display_name.trim() || null,
      description: editForm.description.trim() || null,
    }
    await apiFetch<ModelHub>(`/model-hub/models/${selectedModel.value.id}`, { method: 'PATCH', body: { ...body } })
    editDialog.value = false
    await loadModels()
    ElMessage.success('模型已更新')
  } catch (error) {
    ElMessage.error(friendlyError(error))
  } finally {
    saving.value = false
  }
}

async function setStatus(model: ModelHub, isActive: boolean) {
  try {
    await apiFetch<ModelHub>(`/model-hub/models/${model.id}/status`, {
      method: 'POST',
      body: { is_active: isActive },
    })
    await loadModels()
    ElMessage.success(isActive ? '模型已启用' : '模型已停用')
  } catch (error) {
    ElMessage.error(friendlyError(error))
  }
}

async function openChannels(model: ModelHub) {
  selectedModel.value = model
  channelDrawer.value = true
  channelLoading.value = true
  try {
    channels.value = await apiFetch<ModelChannel[]>(`/model-hub/models/${model.id}/channels`)
  } catch (error) {
    ElMessage.error(friendlyError(error))
  } finally {
    channelLoading.value = false
  }
}

function openConnect(item: ModelCatalog) {
  selectedCatalog.value = item
  connectError.value = ''
  connectForm.runtime_name = item.model_code
  connectForm.api_key = ''
  connectForm.base_url = item.default_base_url
  connectForm.weight = 1
  connectDialog.value = true
}

function resetConnectForm() {
  selectedCatalog.value = null
  connectError.value = ''
  connectForm.runtime_name = ''
  connectForm.api_key = ''
  connectForm.base_url = ''
  connectForm.weight = 1
}

async function connectCatalogModel() {
  if (!selectedCatalog.value) return
  connectError.value = ''
  if (!connectForm.runtime_name.trim()) {
    connectError.value = '请填写内部模型名'
    return
  }
  if (!connectForm.api_key.trim()) {
    connectError.value = '请填写 API Key'
    return
  }
  connecting.value = true
  try {
    const body: ModelCenterConnectRequest = {
      runtime_name: connectForm.runtime_name.trim(),
      api_key: connectForm.api_key,
      base_url: connectForm.base_url.trim() || null,
      weight: connectForm.weight || 1,
      test_after_create: true,
    }
    const result = await apiFetch<ModelCenterConnectResponse>(`/model-center/catalog/${selectedCatalog.value.id}/connect`, {
      method: 'POST',
      body: { ...body },
    })
    connectDialog.value = false
    resetConnectForm()
    await loadModels()
    ElMessage.success(result.test_result.ok ? '模型已接入，连接测试通过' : '模型已接入，但连接测试失败')
  } catch (error) {
    connectError.value = friendlyError(error)
  } finally {
    connecting.value = false
  }
}

async function testChannel(channel: ModelChannel) {
  testingChannelId.value = channel.id
  try {
    const result = await apiFetch<ModelCenterChannelTestResponse>(`/model-center/channels/${channel.id}/test`, {
      method: 'POST',
    })
    const index = channels.value.findIndex((item) => item.id === channel.id)
    if (index >= 0) channels.value[index] = result.channel
    ElMessage[result.test_result.ok ? 'success' : 'error'](
      result.test_result.ok ? '连接测试通过' : `连接测试失败：${result.test_result.error || result.test_result.health}`,
    )
  } catch (error) {
    ElMessage.error(friendlyError(error))
  } finally {
    testingChannelId.value = ''
  }
}

function catalogAvailability(item: ModelCatalog) {
  return String(item.recommended_parameters?.availability || '')
}

function catalogAvailabilityLabel(item: ModelCatalog) {
  const availability = catalogAvailability(item)
  if (availability === 'verified_local') return '可直接体验'
  if (availability === 'needs_real_key') return '需自备 API Key'
  if (availability === 'demo_only') return '仅演示'
  return availability || '待确认'
}

function catalogAvailabilityType(item: ModelCatalog) {
  return catalogAvailability(item)
}

function modelTypeLabel(value: string) {
  const found = modelTypes.find((item) => item.value === value)
  return found?.label || value
}

function formatContextWindow(value?: number | null) {
  if (!value) return '未标注'
  return value >= 1000 ? `${Math.round(value / 1000)}K` : String(value)
}

onMounted(refreshAll)
</script>

<template>
  <section class="model-hub-page">
    <PageHeader title="模型中心" description="统一维护模型目录、供应商接入、运行时模型和默认调用渠道。">
      <template #actions>
        <el-button type="primary" :icon="Plus" @click="createDialog = true">新建模型</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="models.length === 0"
      title="请先在模型中心配置模型 API 并测试连通"
      description="生产模式不会默认返回 mock 假答案。请从模型广场选择 DeepSeek、OpenAI 或通义等真实模型，填入 API Key，通过连接测试后再创建智能体或知识库。"
      type="warning"
      show-icon
      :closable="false"
    />

    <div class="metric-grid model-metrics">
      <section class="panel-card stat-card">
        <span>模型总数</span>
        <strong>{{ models.length }} 个</strong>
      </section>
      <section class="panel-card stat-card">
        <span>启用模型</span>
        <strong>{{ activeCount }} 个</strong>
      </section>
      <section class="panel-card stat-card">
        <span>模型类型</span>
        <strong>{{ new Set(models.map((item) => item.type)).size }} 类</strong>
      </section>
      <section class="panel-card stat-card">
        <span>供应商</span>
        <strong>{{ new Set(models.map((item) => item.provider || 'unknown')).size }} 个</strong>
      </section>
    </div>

    <section class="panel-card catalog-section">
      <SectionHeader title="模型广场" description="查看可接入模型目录，填入密钥后先测试连接，通过后再启用模型。">
        <template #actions>
          <div class="catalog-filters">
          <el-select v-model="catalogFilters.model_type" clearable placeholder="全部类型" @change="loadCatalog">
            <el-option v-for="item in modelTypes" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="catalogFilters.provider" clearable placeholder="全部供应商" @change="loadCatalog">
            <el-option v-for="item in catalogProviders" :key="item" :label="item" :value="item" />
          </el-select>
        </div>
        </template>
      </SectionHeader>

      <div v-loading="catalogLoading" class="catalog-grid">
        <article v-for="item in catalog" :key="item.id" class="catalog-card">
          <div class="catalog-card-head">
            <div>
              <h3>{{ item.display_name }}</h3>
              <span class="catalog-code">{{ item.provider }} · {{ item.model_code }}</span>
            </div>
            <StatusTag :status="catalogAvailabilityType(item)" :label="catalogAvailabilityLabel(item)" />
          </div>
          <p class="catalog-desc">{{ item.description || '暂无简介' }}</p>
          <div class="catalog-meta">
            <span>{{ modelTypeLabel(item.model_type) }}</span>
            <span>{{ item.protocol }}</span>
            <span>上下文 {{ formatContextWindow(item.context_window) }}</span>
          </div>
          <div class="catalog-tags">
            <el-tag v-if="item.supports_streaming" size="small">流式</el-tag>
            <el-tag v-if="item.supports_tools" size="small">工具</el-tag>
            <el-tag v-if="item.supports_vision" size="small">视觉</el-tag>
            <el-tag v-if="!item.supports_streaming && !item.supports_tools && !item.supports_vision" size="small" type="info">
              基础调用
            </el-tag>
          </div>
          <div class="catalog-footer">
            <span>{{ item.default_base_url }}</span>
            <el-button size="small" type="primary" plain @click="openConnect(item)">接入使用</el-button>
          </div>
        </article>
        <EmptyState
          v-if="!catalogLoading && catalog.length === 0"
          class="catalog-empty"
          title="没有匹配的模型目录"
          description="当前筛选条件下没有可接入模型，可以清空类型或供应商筛选后再查看。"
          action-text="刷新目录"
          @action="loadCatalog"
        />
      </div>
    </section>

    <section class="panel-card">
      <SectionHeader title="已接入模型" description="维护运行时使用的逻辑模型和 MaaS 调用渠道。">
        <template #actions>
          <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
        </template>
      </SectionHeader>
      <el-table v-loading="loading" :data="models" border>
        <template #empty>
          <EmptyState title="请先配置真实模型 API" description="生产模式不会静默返回 mock 假答案。请从模型广场接入真实供应商并完成连通性测试。" action-text="刷新模型广场" @action="loadCatalog" />
        </template>
        <el-table-column label="展示名" min-width="180">
          <template #default="{ row }">
            <strong>{{ displayName(row) }}</strong>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="内部模型名" min-width="180" />
        <el-table-column prop="provider" label="供应商" width="140" />
        <el-table-column prop="type" label="类型" width="120" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StatusTag :status="row.is_active === false ? 'disabled' : 'active'" />
          </template>
        </el-table-column>
        <el-table-column prop="import_source" label="来源" width="130" />
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :icon="Edit" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" :icon="Link" @click="openChannels(row)">渠道</el-button>
            <el-button
              size="small"
              :type="row.is_active === false ? 'success' : 'warning'"
              @click="setStatus(row, row.is_active === false)"
            >
              {{ row.is_active === false ? '启用' : '停用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="createDialog" title="新建模型" width="560px" @closed="resetCreateForm">
      <el-form label-width="110px">
        <el-form-item label="模型名" required>
          <el-input v-model="createForm.name" placeholder="runtime 调用名，例如 ui-test-model" />
        </el-form-item>
        <el-form-item label="供应商">
          <el-input v-model="createForm.provider" placeholder="deepseek / openai / qwen" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="createForm.type" class="full-width-control">
            <el-option v-for="item in modelTypes" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="展示名">
          <el-input v-model="createForm.display_name" placeholder="页面展示名称" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="createForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="默认渠道">
          <el-switch v-model="createForm.with_channel" active-text="创建" inactive-text="暂不创建" />
        </el-form-item>
        <template v-if="createForm.with_channel">
          <el-form-item label="渠道地址" required>
            <el-input v-model="createForm.base_url" placeholder="https://api.deepseek.com 或供应商兼容地址" />
          </el-form-item>
          <el-form-item label="密钥" required>
            <el-input v-model="createForm.api_key" type="password" show-password autocomplete="new-password" />
          </el-form-item>
          <el-form-item label="权重">
            <el-input-number v-model="createForm.weight" :min="1" :max="100" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createModel">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="connectDialog" title="接入模型" width="620px" @closed="resetConnectForm">
      <template v-if="selectedCatalog">
        <div class="connect-summary">
          <div>
            <span>模型</span>
            <strong>{{ selectedCatalog.display_name }}</strong>
          </div>
          <div>
            <span>类型</span>
            <strong>{{ modelTypeLabel(selectedCatalog.model_type) }}</strong>
          </div>
          <div>
            <span>供应商</span>
            <strong>{{ selectedCatalog.provider }}</strong>
          </div>
          <div>
            <span>协议</span>
            <strong>{{ selectedCatalog.protocol }}</strong>
          </div>
          <div>
            <span>目录编码</span>
            <strong>{{ selectedCatalog.model_code }}</strong>
          </div>
        </div>
        <el-alert
          :title="`正在接入 ${modelTypeLabel(selectedCatalog.model_type)} 类型模型。知识库 Embedding 下拉只会显示 Embedding 类型，请确认没有从 LLM 目录项接入向量模型。`"
          type="info"
          show-icon
          :closable="false"
          class="connect-error"
        />
        <el-alert
          v-if="connectError"
          :title="connectError"
          type="error"
          show-icon
          :closable="false"
          class="connect-error"
        />
        <el-form label-position="top" class="connect-form">
          <el-form-item label="内部模型名" required>
            <el-input v-model="connectForm.runtime_name" placeholder="智能体运行时选择的模型名" />
          </el-form-item>
          <el-form-item label="默认地址">
            <el-input :model-value="selectedCatalog.default_base_url" readonly />
            <div class="field-help">来自模型目录的预置地址，不会保存密钥。</div>
          </el-form-item>
          <el-form-item label="覆盖地址">
            <el-input v-model="connectForm.base_url" placeholder="不填则使用默认地址" />
            <div class="field-help">私有网关或代理地址可在这里覆盖。</div>
          </el-form-item>
          <el-form-item label="API Key" required>
            <el-input v-model="connectForm.api_key" type="password" show-password autocomplete="new-password" />
            <div class="field-help">仅用于连接测试和 MaaS 加密保存，页面不会回显。</div>
          </el-form-item>
          <el-form-item label="权重">
            <el-input-number v-model="connectForm.weight" :min="1" :max="100" />
          </el-form-item>
        </el-form>
      </template>
      <template #footer>
        <el-button @click="connectDialog = false">取消</el-button>
        <el-button type="primary" :loading="connecting" @click="connectCatalogModel">测试并接入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialog" title="编辑模型" width="520px">
      <el-form label-width="90px">
        <el-form-item label="展示名">
          <el-input v-model="editForm.display_name" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="editForm.description" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="updateModel">保存</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="channelDrawer" :title="`${selectedModel ? displayName(selectedModel) : ''} · 渠道`" size="560px">
      <el-table v-loading="channelLoading" :data="channels" border>
        <el-table-column prop="base_url" label="渠道地址" min-width="220" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <StatusTag :status="row.status || 'unknown'" />
          </template>
        </el-table-column>
        <el-table-column label="健康" width="110">
          <template #default="{ row }">
            <StatusTag :status="row.health || 'unknown'" />
          </template>
        </el-table-column>
        <el-table-column prop="weight" label="权重" width="80" />
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :loading="testingChannelId === row.id" @click="testChannel(row)">重新测试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>
  </section>
</template>

<style scoped>
.model-hub-page {
  display: grid;
  gap: var(--space-6);
}

.model-hub-page .panel-card {
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  padding: var(--space-5);
  box-shadow: var(--shadow-card);
}

.model-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
}

.model-metrics .stat-card {
  height: 132px;
}

.model-metrics .stat-card strong {
  font-size: 30px;
  font-weight: 600;
}

.catalog-section {
  margin-bottom: 0;
}

.catalog-filters {
  display: grid;
  grid-template-columns: 140px 160px;
  gap: var(--space-2);
}

.catalog-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
  min-height: 120px;
}

.catalog-card {
  display: flex;
  min-height: 250px;
  flex-direction: column;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-5);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  transition:
    border-color 0.16s ease,
    box-shadow 0.16s ease;
}

.catalog-card:hover {
  border-color: var(--color-brand-secondary);
  box-shadow: var(--shadow-card-hover);
}

.catalog-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.catalog-card h3 {
  margin: 0 0 var(--space-1);
  color: var(--color-text-primary);
  font-size: var(--font-size-card-title);
  font-weight: 600;
  line-height: 1.4;
}

.catalog-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}

.catalog-card-head .catalog-code,
.catalog-footer span {
  color: var(--color-text-tertiary);
  font-size: 13px;
}

.catalog-desc {
  min-height: 44px;
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.55;
}

.catalog-meta,
.catalog-tags,
.catalog-footer {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.catalog-meta span {
  padding: 3px var(--space-2);
  border-radius: var(--radius-pill);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
  font-size: 12px;
}

.catalog-footer {
  justify-content: space-between;
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-subtle);
}

.catalog-footer span {
  max-width: 70%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog-empty {
  grid-column: 1 / -1;
}

:deep(.el-table__header th) {
  height: 44px;
}

:deep(.el-table__row) {
  height: 52px;
}

.connect-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  background: var(--color-bg-subtle);
}

.connect-summary div {
  display: grid;
  gap: var(--space-1);
}

.connect-summary span {
  color: var(--color-text-tertiary);
  font-size: 12px;
}

.connect-summary strong {
  overflow: hidden;
  color: var(--color-text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.connect-error {
  margin-bottom: var(--space-4);
}

.field-help {
  margin-top: var(--space-1);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-help);
}

.full-width-control {
  width: 100%;
}

@media (max-width: 1280px) {
  .catalog-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .model-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 860px) {
  .model-metrics,
  .catalog-filters,
  .catalog-grid {
    grid-template-columns: 1fr;
    width: 100%;
  }
}
</style>
