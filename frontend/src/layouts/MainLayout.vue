<script setup lang="ts">
import {
  Blocks,
  Bot,
  BriefcaseBusiness,
  BookOpen,
  ChartNoAxesColumnIncreasing,
  ChevronUp,
  ClipboardCheck,
  Database,
  Factory,
  FileCheck2,
  Gauge,
  Hammer,
  LayoutTemplate,
  LogOut,
  MessageSquareText,
  Rocket,
  Settings,
  ShieldCheck,
  Users,
} from 'lucide-vue-next'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const navGroups = [
  {
    label: '工作台',
    items: [
      { path: '/quickstart', label: '快速开始', icon: Rocket, permissions: ['dashboard:view'] },
      { path: '/dashboard', label: '首页工作台', icon: Gauge, permissions: ['dashboard:view'] },
    ],
  },
  {
    label: '构建',
    items: [
      { path: '/factory', label: '智能体工厂', icon: Factory, permissions: ['agent:publish'] },
      { path: '/agents', label: '智能体管理', icon: Bot, permissions: ['agent:publish'] },
      { path: '/templates', label: '模板广场', icon: LayoutTemplate, permissions: ['agent:publish'] },
      { path: '/chat', label: '对话验证', icon: MessageSquareText, permissions: ['dashboard:view'] },
    ],
  },
  {
    label: 'AI资源',
    items: [
      { path: '/model-hub', label: '模型中心', icon: Blocks, permissions: ['maas:admin'] },
      { path: '/kbs', label: '知识库实验台', icon: Database, permissions: ['kb:create'] },
      { path: '/tools', label: '工具中心', icon: Hammer, permissions: ['agent:publish'] },
    ],
  },
  {
    label: '运营',
    items: [
      { path: '/publish', label: '发布中心', icon: FileCheck2, permissions: ['agent:publish'] },
      { path: '/observability', label: '观测中心', icon: ChartNoAxesColumnIncreasing, permissions: ['dashboard:view'] },
    ],
  },
  {
    label: '管理',
    items: [
      { path: '/workspaces', label: '工作空间', icon: BriefcaseBusiness, permissions: ['dashboard:view'] },
      { path: '/audit', label: '审计记录', icon: ClipboardCheck, permissions: ['audit:view'] },
    ],
  },
]

const adminMenuItems = [
  { path: '/admin/users', label: '用户管理', icon: Users, permissions: ['user:view'] },
  { path: '/admin/roles', label: '角色权限', icon: ShieldCheck, permissions: ['role:view', 'permission:view'] },
  { path: '/workspaces', label: '工作空间', icon: BriefcaseBusiness, permissions: ['dashboard:view'] },
  { path: '/publish', label: '发布版本', icon: FileCheck2, permissions: ['agent:publish'] },
  { path: '/audit', label: '审计记录', icon: ClipboardCheck, permissions: ['audit:view'] },
  { path: '/admin/settings', label: '系统设置', icon: Settings, permissions: ['tenant:update'] },
]

const roleLabels: Record<string, string> = {
  super_admin: `平台${'管理员'}`,
  tenant_admin: '租户管理员',
  builder: '构建者',
  member: '普通成员',
}

function canAccess(permissions?: string[]) {
  if (!permissions?.length) return true
  const granted = auth.user?.permissions || []
  return permissions.every((permission) => granted.includes(permission))
}

const visibleNavGroups = computed(() =>
  navGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => canAccess(item.permissions)),
    }))
    .filter((group) => group.items.length > 0),
)
const visibleAdminMenuItems = computed(() => adminMenuItems.filter((item) => canAccess(item.permissions)))
const activePath = computed(() => (route.path.startsWith('/admin/') ? route.path : `/${String(route.path.split('/')[1] || 'dashboard')}`))
const activeItem = computed(() => [...navGroups.flatMap((group) => group.items), ...adminMenuItems].find((item) => item.path === activePath.value))
const topbarTitle = computed(() => (route.path.startsWith('/guide') ? '使用教程' : activeItem.value?.label || '首页工作台'))
const roleText = computed(() => (auth.user?.roles || []).map((role) => roleLabels[role] || role).join(' / ') || '未登录')
const tenantShort = computed(() => {
  const tenantId = auth.user?.tenant_id || 'default'
  return tenantId === 'default' ? 'default' : tenantId.slice(0, 8)
})

function handleAdminCommand(command: string) {
  if (command === 'logout') {
    logout()
    return
  }
  router.push(command)
}

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <main class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">AI</div>
        <div>
          <strong>企业智能体中台</strong>
          <span>AI SaaS Console</span>
        </div>
      </div>

      <nav class="nav-list" aria-label="主导航">
        <section v-for="group in visibleNavGroups" :key="group.label" class="nav-group">
          <div class="nav-group-title">{{ group.label }}</div>
          <RouterLink
            v-for="item in group.items"
            :key="item.path"
            class="nav-item"
            :class="{ active: activePath === item.path }"
            :to="item.path"
          >
            <component :is="item.icon" class="nav-icon" :size="18" :stroke-width="1.9" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>
      </nav>

      <el-dropdown trigger="click" placement="top-start" @command="handleAdminCommand">
        <button class="account-entry" type="button">
          <div class="account-avatar">{{ auth.displayName.slice(0, 1).toUpperCase() }}</div>
          <div>
            <strong>{{ roleText }}</strong>
            <span>{{ auth.displayName }} · 企业 {{ tenantShort }}</span>
          </div>
          <ChevronUp class="account-chevron" :size="16" />
        </button>
        <template #dropdown>
          <el-dropdown-menu class="admin-dropdown-menu">
            <el-dropdown-item v-for="item in visibleAdminMenuItems" :key="item.path" :command="item.path">
              <component :is="item.icon" :size="16" />
              {{ item.label }}
            </el-dropdown-item>
            <el-dropdown-item divided command="logout">
              <LogOut :size="16" />
              退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </aside>

    <section class="main">
      <header class="topbar">
        <div>
          <strong>{{ topbarTitle }}</strong>
          <span>当前工作空间：默认项目 · 企业 {{ auth.user?.tenant_id || 'default' }}</span>
        </div>
        <div class="topbar-actions">
          <el-tooltip content="使用教程" placement="bottom">
            <el-button circle :type="route.path.startsWith('/guide') ? 'primary' : 'default'" @click="router.push('/guide')">
              <BookOpen :size="18" />
            </el-button>
          </el-tooltip>
        </div>
      </header>

      <RouterView />
    </section>
  </main>
</template>
