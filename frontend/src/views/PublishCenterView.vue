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
const keyForm = ref({ name: '默认访问密钥' })
const selectedAgent = computed(() => agents.value.find((agent) => agent.id === selectedAgentId.value) || null)
const selectedApp = computed(() => apps.value.find((app) => app.id === selectedAppId.value) || apps.value[0] || null)
const openAiBaseUrl = computed(() => {
  const appId = selectedApp.value?.id || '<app_id>'
  return `${window.location.origin}/api/v1/public/apps/${appId}/openai/v1`
})
const openAiModel = computed(() => (selectedApp.value ? agentName(selectedApp.value.agent_id) : '<model>'))
const openAiExample = computed(() => `from openai import OpenAI

client = OpenAI(
    base_url="${openAiBaseUrl.value}",
    api_key="${oneTimeKey.value || '<api_key>'}",
)

response = client.chat.completions.create(
    model="${openAiModel.value}",
    messages=[{"role": "user", "content": "请介绍这个应用能做什么"}],
)
print(response.choices[0].message.content)`)

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
        name: `${selectedAgent.value.name} 外部应用`,
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
  keyForm.value.name = `${app.name} 访问密钥`
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
    ElMessage.success('访问密钥已生成')
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

async function copyOpenAiExample() {
  await navigator.clipboard?.writeText(openAiExample.value)
  ElMessage.success('调用示例已复制')
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
    agent_not_found: '未找到该智能体，请刷新后重试。',
    agent_not_publishable: '智能体需要先发布为可用状态，再发布为外部应用。',
    published_app_not_found: '发布应用不存在。',
    published_app_not_active: '应用未发布，不能生成访问密钥。',
  }
  return map[message] || message
}

onMounted(loadData)
</script>

<template>
  <section class="page">
    <PageHeader title="发布中心" description="将已验证的智能体发布为外部应用，并管理访问密钥。">
      <template #actions>
        <el-button @click="loadData">刷新</el-button>
      </template>
    </PageHeader>

    <section class="panel-card">
      <SectionHeader title="发布外部应用" description="选择一个已启用智能体，生成可管理的发布记录。">
        <template #actions>
        <el-button type="primary" :loading="publishing" :disabled="!selectedAgentId" @click="publishSelectedAgent">
          发布为外部应用
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
      <SectionHeader title="已发布应用" description="访问密钥只在生成时完整展示一次，列表仅显示前缀。" />
      <el-table v-loading="loading" :data="apps" border>
        <template #empty>
          <EmptyState title="还没有发布应用" description="请先选择一个已启用智能体，将它发布为外部应用。" />
        </template>
        <el-table-column prop="name" label="应用" min-width="180" />
        <el-table-column label="智能体" min-width="180">
          <template #default="{ row }">{{ agentName(row.agent_id) }}</template>
        </el-table-column>
        <el-table-column prop="publish_type" label="发布方式" width="100" />
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
            <el-button size="small" @click="openCreateKey(row)">生成密钥</el-button>
            <el-button size="small" @click="loadKeys(row.id)">刷新密钥</el-button>
            <el-button v-if="row.status === 'published'" size="small" @click="unpublish(row)">下线</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="panel-card">
      <SectionHeader title="访问密钥列表" description="这里只显示密钥前缀，完整密钥只在生成后展示一次。" />
      <EmptyState v-if="apps.length === 0" title="还没有已发布应用" description="请先发布应用，再生成和管理访问密钥。" />
      <el-collapse v-else accordion>
        <el-collapse-item v-for="app in apps" :key="app.id" :title="`${app.name} · ${app.status}`" :name="app.id">
          <el-table :data="keysByApp[app.id] || []" border>
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column label="密钥前缀" min-width="150">
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

    <el-dialog v-model="keyDialog" title="生成访问密钥" width="560px">
      <el-form label-position="top">
        <el-form-item label="密钥名称">
          <el-input v-model="keyForm.name" />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="oneTimeKey"
        title="访问密钥只展示这一次。关闭弹窗后只能查看前缀，不能再次查看完整密钥。"
        type="warning"
        :closable="false"
        show-icon
      />
      <el-input v-if="oneTimeKey" v-model="oneTimeKey" class="mt one-time-key" readonly type="textarea" :rows="3" />
      <section v-if="oneTimeKey" class="openai-example mt">
        <SectionHeader title="OpenAI 兼容调用" description="按以下 base_url、api_key、model 接入现有 OpenAI SDK。" />
        <div class="example-fields">
          <div><span>base_url</span><code>{{ openAiBaseUrl }}</code></div>
          <div><span>api_key</span><code>{{ oneTimeKey }}</code></div>
          <div><span>model</span><code>{{ openAiModel }}</code></div>
        </div>
        <el-input :model-value="openAiExample" readonly type="textarea" :rows="9" />
        <el-button class="mt" @click="copyOpenAiExample">复制调用示例</el-button>
      </section>
      <template #footer>
        <el-button @click="keyDialog = false">关闭</el-button>
        <el-button v-if="oneTimeKey" @click="copyOneTimeKey">复制密钥</el-button>
        <el-button v-else type="primary" :loading="creatingKey" @click="createKey">生成</el-button>
      </template>
    </el-dialog>
  </section>
</template>
