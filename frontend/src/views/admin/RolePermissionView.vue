<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { apiFetch } from '../../api/client'
import PageHeader from '../../components/common/PageHeader.vue'
import SectionHeader from '../../components/common/SectionHeader.vue'
import type { Permission, Role } from '../../api/types'

const roles = ref<Role[]>([])
const permissions = ref<Permission[]>([])
const loading = ref(false)

const permissionModules = computed(() => Array.from(new Set(permissions.value.map((item) => item.module || '其他权限'))).sort())

async function loadData() {
  loading.value = true
  try {
    const [roleRows, permissionRows] = await Promise.all([apiFetch<Role[]>('/roles'), apiFetch<Permission[]>('/permissions')])
    roles.value = roleRows
    permissions.value = permissionRows
  } catch (error) {
    ElMessage.error(formatAdminError(error))
  } finally {
    loading.value = false
  }
}

function formatAdminError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || '请求失败')
  const map: Record<string, string> = {
    permission_denied: '当前账号没有查看角色权限的权限。',
  }
  return map[message] || message
}

onMounted(loadData)
</script>

<template>
  <section class="admin-page">
    <PageHeader title="角色权限" description="查看平台预设角色与权限范围，便于为企业成员分配合适的管理职责。">
      <template #actions>
        <el-button :icon="Refresh" @click="loadData">刷新</el-button>
      </template>
    </PageHeader>

    <div class="admin-role-grid">
      <section class="panel-card">
        <SectionHeader title="角色列表" description="角色用于定义成员可承担的职责范围。" />
        <el-table v-loading="loading" :data="roles" border>
          <el-table-column prop="name" label="角色名称" min-width="160" />
          <el-table-column prop="code" label="角色标识" min-width="180" />
        </el-table>
      </section>

      <section class="panel-card">
        <SectionHeader title="权限列表" description="权限用于控制用户可查看或操作的平台能力。" />
        <div v-loading="loading" class="permission-groups">
          <section v-for="moduleName in permissionModules" :key="moduleName" class="permission-group">
            <h3>{{ moduleName }}</h3>
            <div class="permission-tags">
              <el-tag
                v-for="permission in permissions.filter((item) => (item.module || '其他权限') === moduleName)"
                :key="permission.code"
                effect="plain"
              >
                {{ permission.name || permission.code }}
              </el-tag>
            </div>
          </section>
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

.admin-role-grid {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(0, 1.4fr);
  gap: var(--space-4);
}

.permission-groups {
  display: grid;
  gap: var(--space-4);
}

.permission-group {
  display: grid;
  gap: var(--space-2);
}

.permission-group h3 {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-body);
  font-weight: 600;
}

.permission-tags {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

@media (max-width: 1100px) {
  .admin-role-grid {
    grid-template-columns: 1fr;
  }
}
</style>
