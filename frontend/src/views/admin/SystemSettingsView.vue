<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { apiFetch } from '../../api/client'
import PageHeader from '../../components/common/PageHeader.vue'
import SectionHeader from '../../components/common/SectionHeader.vue'
import StatusTag from '../../components/common/StatusTag.vue'
import { useAuthStore } from '../../stores/auth'
import type { Tenant } from '../../api/types'

const auth = useAuthStore()
const tenants = ref<Tenant[]>([])
const loading = ref(false)

const currentTenant = computed(() => tenants.value.find((tenant) => tenant.id === auth.user?.tenant_id) || null)
const tenantName = computed(() => currentTenant.value?.name || '当前企业')
const tenantCode = computed(() => currentTenant.value?.code || auth.user?.tenant_id || 'default')

async function loadTenantInfo() {
  loading.value = true
  try {
    tenants.value = await apiFetch<Tenant[]>('/tenants')
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error || '')
    if (message !== 'permission_denied') {
      ElMessage.error(message || '企业信息加载失败')
    }
  } finally {
    loading.value = false
  }
}

onMounted(loadTenantInfo)
</script>

<template>
  <section class="admin-page">
    <PageHeader title="系统设置" description="查看当前企业的基础信息，并预留平台运行设置入口。">
      <template #actions>
        <el-button :icon="Refresh" @click="loadTenantInfo">刷新</el-button>
      </template>
    </PageHeader>

    <div class="admin-settings-grid">
      <section v-loading="loading" class="panel-card">
        <SectionHeader title="当前企业" description="用于确认当前登录账号所属企业与账号身份。" />
        <dl class="settings-list">
          <div>
            <dt>企业名称</dt>
            <dd>{{ tenantName }}</dd>
          </div>
          <div>
            <dt>企业标识</dt>
            <dd>{{ tenantCode }}</dd>
          </div>
          <div>
            <dt>企业状态</dt>
            <dd>
              <StatusTag :status="currentTenant?.status || 'active'" />
            </dd>
          </div>
          <div>
            <dt>当前账号</dt>
            <dd>{{ auth.displayName }}</dd>
          </div>
          <div>
            <dt>账号角色</dt>
            <dd>{{ auth.user?.roles?.join('、') || '未配置角色' }}</dd>
          </div>
        </dl>
      </section>

      <section class="panel-card">
        <SectionHeader title="基础设置" description="以下设置项用于后续统一管理平台运行偏好。" />
        <div class="setting-items">
          <article>
            <strong>企业默认工作空间</strong>
            <span>当前使用“默认项目”作为进入平台后的默认工作空间。</span>
          </article>
          <article>
            <strong>安全策略</strong>
            <span>账号状态、角色授权和审计记录已接入平台权限体系。</span>
          </article>
          <article>
            <strong>通知设置</strong>
            <span>预留模型接入、发布版本和知识库处理结果的通知配置。</span>
          </article>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.admin-page {
  display: grid;
  gap: var(--space-6);
}

.admin-settings-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.8fr);
  gap: var(--space-4);
}

.settings-list {
  display: grid;
  gap: var(--space-3);
  margin: 0;
}

.settings-list div,
.setting-items article {
  display: grid;
  gap: var(--space-1);
  border-bottom: 1px solid var(--color-border-subtle);
  padding-bottom: var(--space-3);
}

.settings-list div:last-child,
.setting-items article:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.settings-list dt {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-help);
}

.settings-list dd {
  margin: 0;
  color: var(--color-text-primary);
  font-weight: 600;
}

.setting-items {
  display: grid;
  gap: var(--space-3);
}

.setting-items strong {
  color: var(--color-text-primary);
  font-weight: 600;
}

.setting-items span {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-help);
  line-height: 1.7;
}

@media (max-width: 1100px) {
  .admin-settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
