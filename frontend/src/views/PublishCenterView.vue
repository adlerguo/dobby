<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { apiFetch } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import PageHeader from '../components/common/PageHeader.vue'
import SectionHeader from '../components/common/SectionHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'
import type { Agent, AppApiKey, AppApiKeyCreated, PublishedApp } from '../api/types'

const agents = ref<Agent[]>([])
const apps = ref<PublishedApp[]>([])
const keysByApp = ref<Record<string, AppApiKey[]>>({})
const selectedAgentId = ref('')
const selectedAppId = ref('')
const loading = ref(false)
const publishing = ref(false)
const creatingKey = ref(false)
const keyDialog = ref(false)
const oneTimeKey = ref('')
const keyForm = ref({ name: '默认 API Key' })
const selectedAgent = computed(() => agents.value.find((agent) => agent.id === selectedAgentId.value) || null)
const selectedApp = computed(() => apps.value.find((app) => app.id === selectedAppId.value) || apps.value[0] || null)

async function loadData() {
  loading.value = true
  try {
    const [agentRows, appRows] = await Promise.all([
      apiFetch<Agent[]>('/agents'),
      apiFetch<PublishedApp[]>('/published-apps'),
    ])
    agents.value = agentRows
    apps.value = appRows
    selectedAgentId.value = selectedAgentId.value || agents.value.find((agent) => agent.status === 'active')?.id || ''
    selectedAppId.value = selectedAppId.value || apps.value[0]?.id || ''
    await Promise.all(apps.value.slice(0, 6).map((app) => loadKeys(app.id)))
  } finally {
    loading.value = false
  }
}

async function publishSelectedAgent() {
  if (!selectedAgent.value) return
  publishing.value = true
  try {
    const app = await apiFetch<PublishedApp>('/published-apps', {
      method: 'POST',
      body: {
        agent_id: selectedAgent.value.id,
        name: `${selectedAgent.value.name} API`,
        publish_type: 'api',
        config: {},
      },
    })
    ElMessage.success('应用已发布')
    selectedAppId.value = app.id
    await loadData()
  } catch (error) {
    ElMessage.error(formatPublishError(error))
  } finally {
    publishing.value = false
  }
}

async function unpublish(app: PublishedApp) {
  try {
    await apiFetch<PublishedApp>(`/published-apps/${app.id}/unpublish`, { method: 'POST', body: {} })
    ElMessage.success('应用已下线')
    await loadData()
  } catch (error) {
    ElMessage.error(formatPublishError(error))
  }
}

async function loadKeys(appId: string) {
  keysByApp.value[appId] = await apiFetch<AppApiKey[]>(`/published-apps/${appId}/keys`)
}

function openCreateKey(app: PublishedApp) {
  selectedAppId.value = app.id
  keyForm.value.name = `${app.name} Key`
  oneTimeKey.value = ''
  keyDialog.value = true
}

async function createKey() {
  if (!selectedApp.value) return
  creatingKey.value = true
  try {
    const created = await apiFetch<AppApiKeyCreated>(`/published-apps/${selectedApp.value.id}/keys`, {
      method: 'POST',
      body: { name: keyForm.value.name },
    })
    oneTimeKey.value = created.api_key
    await loadKeys(selectedApp.value.id)
    ElMessage.success('API Key 已生成')
  } catch (error) {
    ElMessage.error(formatPublishError(error))
  } finally {
    creatingKey.value = false
  }
}

async function setKeyStatus(app: PublishedApp, key: AppApiKey, status: 'active' | 'disabled') {
  try {
    await apiFetch<AppApiKey>(`/published-apps/${app.id}/keys/${key.id}/status`, {
      method: 'POST',
      body: { status },
    })
    await loadKeys(app.id)
  } catch (error) {
    ElMessage.error(formatPublishError(error))
  }
}

async function copyOneTimeKey() {
  if (!oneTimeKey.value) return
  await navigator.clipboard?.writeText(oneTimeKey.value)
  ElMessage.success('已复制')
}

function agentName(agentId: string) {
  return agents.value.find((agent) => agent.id === agentId)?.name || agentId
}

function formatDate(value?: string | null) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function formatPublishError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || '请求失败')
  const map: Record<string, string> = {
    agent_not_found: '智能体不存在或不属于当前租户。',
    agent_not_publishable: '智能体需要先发布为可用状态，再发布成 API 应用。',
    published_app_not_found: '发布应用不存在。',
    published_app_not_active: '应用未发布，不能生成 API Key。',
  }
  return map[message] || message
}

onMounted(loadData)
</script>

<template>
  <section class="page">
    <PageHeader title="发布中心" description="把已调试通过的智能体发布为 API 应用，并管理外部调用 Key。">
      <template #actions>
        <el-button @click="loadData">刷新</el-button>
      </template>
    </PageHeader>

    <section class="panel-card">
      <SectionHeader title="发布 API 应用" description="选择一个 active 智能体，生成可管理的 API 发布记录。">
        <template #actions>
        <el-button type="primary" :loading="publishing" :disabled="!selectedAgentId" @click="publishSelectedAgent">
          发布为 API
        </el-button>
        </template>
      </SectionHeader>
      <div class="grid two">
        <el-select v-model="selectedAgentId" placeholder="选择智能体">
          <el-option
            v-for="agent in agents"
            :key="agent.id"
            :label="`${agent.name} · ${agent.status}`"
            :value="agent.id"
          />
        </el-select>
        <el-alert
          :title="selectedAgent ? `当前选择：${selectedAgent.name}，状态 ${selectedAgent.status}` : '请选择智能体'"
          type="info"
          :closable="false"
        />
      </div>
    </section>

    <section class="panel-card">
      <SectionHeader title="已发布应用" description="API Key 明文只在生成时展示一次，列表只显示前缀。" />
      <el-table v-loading="loading" :data="apps" border>
        <template #empty>
          <EmptyState title="还没有发布应用" description="选择一个可用智能体，将它发布为对外 API 应用。" />
        </template>
        <el-table-column prop="name" label="应用" min-width="180" />
        <el-table-column label="智能体" min-width="180">
          <template #default="{ row }">{{ agentName(row.agent_id) }}</template>
        </el-table-column>
        <el-table-column prop="publish_type" label="渠道" width="100" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StatusTag :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="190">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button size="small" @click="openCreateKey(row)">生成 Key</el-button>
            <el-button size="small" @click="loadKeys(row.id)">刷新 Key</el-button>
            <el-button v-if="row.status === 'published'" size="small" @click="unpublish(row)">下线</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="panel-card">
      <SectionHeader title="API Key 列表" description="只显示 Key 前缀，完整 Key 只在生成后展示一次。" />
      <EmptyState v-if="apps.length === 0" title="暂无已发布应用" description="发布应用后即可生成和管理 API Key。" />
      <el-collapse v-else accordion>
        <el-collapse-item v-for="app in apps" :key="app.id" :title="`${app.name} · ${app.status}`" :name="app.id">
          <el-table :data="keysByApp[app.id] || []" border>
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column label="Key 前缀" min-width="150">
              <template #default="{ row }">
                <span class="mono-id">{{ row.key_prefix }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <StatusTag :status="row.status" />
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="190">
              <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="140">
              <template #default="{ row }">
                <el-button
                  size="small"
                  @click="setKeyStatus(app, row, row.status === 'active' ? 'disabled' : 'active')"
                >
                  {{ row.status === 'active' ? '停用' : '启用' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </section>

    <el-dialog v-model="keyDialog" title="生成 API Key" width="560px">
      <el-form label-position="top">
        <el-form-item label="Key 名称">
          <el-input v-model="keyForm.name" />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="oneTimeKey"
        title="API Key 明文只展示这一次。关闭弹窗后只能查看前缀，不能再次查看完整 Key。"
        type="warning"
        :closable="false"
        show-icon
      />
      <el-input v-if="oneTimeKey" v-model="oneTimeKey" class="mt one-time-key" readonly type="textarea" :rows="3" />
      <template #footer>
        <el-button @click="keyDialog = false">关闭</el-button>
        <el-button v-if="oneTimeKey" @click="copyOneTimeKey">复制 Key</el-button>
        <el-button v-else type="primary" :loading="creatingKey" @click="createKey">生成</el-button>
      </template>
    </el-dialog>
  </section>
</template>
