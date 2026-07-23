<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Edit, Plus, Refresh, UserFilled } from '@element-plus/icons-vue'

import { apiFetch } from '../../api/client'
import PageHeader from '../../components/common/PageHeader.vue'
import SectionHeader from '../../components/common/SectionHeader.vue'
import StatusTag from '../../components/common/StatusTag.vue'
import type { AssignRolesOut, PlatformUser, PlatformUserCreate, PlatformUserUpdate, Role } from '../../api/types'

const users = ref<PlatformUser[]>([])
const roles = ref<Role[]>([])
const loading = ref(false)
const saving = ref(false)
const assigning = ref(false)
const userDialog = ref(false)
const roleDialog = ref(false)
const editingUser = ref<PlatformUser | null>(null)
const selectedUser = ref<PlatformUser | null>(null)
const selectedRoleCodes = ref<string[]>([])
const roleCodesByUser = ref<Record<string, string[]>>({})
const userFormRef = ref<FormInstance>()

const userForm = reactive({
  username: '',
  password: '',
  display_name: '',
  email: '',
  status: 'active' as 'active' | 'disabled',
})

const userRules = computed<FormRules>(() => ({
  username: editingUser.value ? [] : [{ required: true, message: '请输入登录账号', trigger: 'blur' }],
  password: editingUser.value
    ? []
    : [
        { required: true, message: '请输入初始密码', trigger: 'blur' },
        { min: 8, message: '初始密码至少 8 位', trigger: 'blur' },
      ],
  display_name: [{ required: true, message: '请输入显示名称', trigger: 'blur' }],
}))

function resetUserForm() {
  userForm.username = ''
  userForm.password = ''
  userForm.display_name = ''
  userForm.email = ''
  userForm.status = 'active'
}

function openCreateDialog() {
  editingUser.value = null
  resetUserForm()
  userDialog.value = true
}

function openEditDialog(user: PlatformUser) {
  editingUser.value = user
  userForm.username = user.username
  userForm.password = ''
  userForm.display_name = user.display_name || ''
  userForm.email = user.email || ''
  userForm.status = user.status === 'disabled' ? 'disabled' : 'active'
  userDialog.value = true
}

function openRoleDialog(user: PlatformUser) {
  selectedUser.value = user
  selectedRoleCodes.value = [...(roleCodesByUser.value[user.id] || [])]
  roleDialog.value = true
}

async function loadData() {
  loading.value = true
  try {
    const [userRows, roleRows] = await Promise.all([apiFetch<PlatformUser[]>('/users'), apiFetch<Role[]>('/roles')])
    users.value = userRows
    roles.value = roleRows
  } catch (error) {
    ElMessage.error(formatAdminError(error))
  } finally {
    loading.value = false
  }
}

async function saveUser() {
  const valid = await userFormRef.value?.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    if (editingUser.value) {
      const payload: PlatformUserUpdate = {
        display_name: userForm.display_name,
        email: userForm.email || null,
        status: userForm.status,
      }
      await apiFetch<PlatformUser>(`/users/${editingUser.value.id}`, {
        method: 'PATCH',
        body: { ...payload },
      })
      ElMessage.success('用户信息已更新')
    } else {
      const payload: PlatformUserCreate = {
        username: userForm.username,
        password: userForm.password,
        display_name: userForm.display_name,
        email: userForm.email || null,
      }
      await apiFetch<PlatformUser>('/users', {
        method: 'POST',
        body: { ...payload },
      })
      ElMessage.success('用户已创建')
    }
    userDialog.value = false
    await loadData()
  } catch (error) {
    ElMessage.error(formatAdminError(error))
  } finally {
    saving.value = false
  }
}

async function assignRoles() {
  if (!selectedUser.value || selectedRoleCodes.value.length === 0) {
    ElMessage.warning('请至少选择一个角色')
    return
  }
  assigning.value = true
  try {
    const result = await apiFetch<AssignRolesOut>(`/users/${selectedUser.value.id}/roles`, {
      method: 'POST',
      body: { role_codes: selectedRoleCodes.value },
    })
    roleCodesByUser.value = {
      ...roleCodesByUser.value,
      [selectedUser.value.id]: result.role_codes,
    }
    ElMessage.success('角色已授予')
    roleDialog.value = false
  } catch (error) {
    ElMessage.error(formatAdminError(error))
  } finally {
    assigning.value = false
  }
}

function roleName(code: string) {
  return roles.value.find((role) => role.code === code)?.name || code
}

function formatAdminError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error || '请求失败')
  const map: Record<string, string> = {
    username_exists: '登录账号已存在，请更换后重试。',
    permission_denied: '当前账号没有执行该操作的权限。',
    user_not_found: '用户不存在，请刷新后重试。',
  }
  return map[message] || message
}

onMounted(loadData)
</script>

<template>
  <section class="admin-page">
    <PageHeader title="用户管理" description="管理企业成员账号，维护账号状态，并为成员授予适合其职责的角色。">
      <template #actions>
        <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreateDialog">新建用户</el-button>
      </template>
    </PageHeader>

    <section class="panel-card">
      <SectionHeader title="用户列表" description="查看当前企业下的成员账号，按需要编辑资料或授予角色。" />
      <el-table v-loading="loading" :data="users" border>
        <el-table-column label="用户" min-width="220">
          <template #default="{ row }">
            <div class="admin-user-cell">
              <strong>{{ row.display_name || row.username }}</strong>
              <span>{{ row.username }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="220">
          <template #default="{ row }">{{ row.email || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <StatusTag :status="row.status || 'active'" />
          </template>
        </el-table-column>
        <el-table-column label="本次授予角色" min-width="220">
          <template #default="{ row }">
            <div v-if="roleCodesByUser[row.id]?.length" class="admin-role-tags">
              <el-tag v-for="code in roleCodesByUser[row.id]" :key="code" size="small">{{ roleName(code) }}</el-tag>
            </div>
            <span v-else class="muted">可通过“分配角色”授予</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="Edit" @click="openEditDialog(row)">编辑</el-button>
            <el-button link type="primary" :icon="UserFilled" @click="openRoleDialog(row)">分配角色</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="userDialog" :title="editingUser ? '编辑用户' : '新建用户'" width="520px">
      <el-form ref="userFormRef" :model="userForm" :rules="userRules" label-position="top">
        <el-form-item label="登录账号" prop="username">
          <el-input v-model="userForm.username" :disabled="Boolean(editingUser)" placeholder="请输入登录账号" />
        </el-form-item>
        <el-form-item v-if="!editingUser" label="初始密码" prop="password">
          <el-input v-model="userForm.password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="显示名称" prop="display_name">
          <el-input v-model="userForm.display_name" placeholder="请输入成员姓名或岗位名称" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="userForm.email" placeholder="请输入邮箱，可选" />
        </el-form-item>
        <el-form-item v-if="editingUser" label="账号状态">
          <el-radio-group v-model="userForm.status">
            <el-radio-button label="active">启用</el-radio-button>
            <el-radio-button label="disabled">停用</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleDialog" title="分配角色" width="520px">
      <div class="admin-dialog-intro">
        <strong>{{ selectedUser?.display_name || selectedUser?.username }}</strong>
        <span>选择该成员需要承担的角色，并保存授权结果。</span>
      </div>
      <el-select v-model="selectedRoleCodes" multiple filterable placeholder="请选择角色" class="admin-role-select">
        <el-option v-for="role in roles" :key="role.code" :label="role.name" :value="role.code">
          <span>{{ role.name }}</span>
          <span class="admin-option-code">{{ role.code }}</span>
        </el-option>
      </el-select>
      <template #footer>
        <el-button @click="roleDialog = false">取消</el-button>
        <el-button type="primary" :loading="assigning" @click="assignRoles">保存角色</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.admin-page {
  display: grid;
  gap: var(--space-6);
}

.admin-user-cell {
  display: grid;
  gap: var(--space-1);
}

.admin-user-cell strong {
  color: var(--color-text-primary);
  font-weight: 600;
}

.admin-user-cell span,
.admin-dialog-intro span,
.admin-option-code {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-help);
}

.admin-role-tags {
  display: flex;
  gap: var(--space-1);
  flex-wrap: wrap;
}

.admin-dialog-intro {
  display: grid;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
}

.admin-role-select {
  width: 100%;
}

.admin-option-code {
  float: right;
  margin-left: var(--space-4);
}
</style>
