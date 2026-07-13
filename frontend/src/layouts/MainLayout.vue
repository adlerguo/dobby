<script setup lang="ts">
import {
  Blocks,
  Bot,
  BriefcaseBusiness,
  ChartNoAxesColumnIncreasing,
  ChevronUp,
  ClipboardCheck,
  Database,
  FileCheck2,
  Gauge,
  Hammer,
  LayoutTemplate,
  LogOut,
  MessageSquareText,
  Search,
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
    items: [{ path: '/dashboard', label: '首页工作台', icon: Gauge }],
  },
  {
    label: '构建',
    items: [
      { path: '/agents', label: '智能体工厂', icon: Bot },
      { path: '/templates', label: '模板广场', icon: LayoutTemplate },
      { path: '/chat', label: '调试对话', icon: MessageSquareText },
    ],
  },
  {
    label: 'AI资源',
    items: [
      { path: '/model-hub', label: '模型中心', icon: Blocks },
      { path: '/kbs', label: '知识库实验台', icon: Database },
      { path: '/tools', label: '工具中心', icon: Hammer },
    ],
  },
  {
    label: '运营',
    items: [
      { path: '/publish', label: '发布中心', icon: FileCheck2 },
      { path: '/observability', label: '观测中心', icon: ChartNoAxesColumnIncreasing },
    ],
  },
  {
    label: '管理',
    items: [
      { path: '/workspaces', label: '工作空间', icon: BriefcaseBusiness },
      { path: '/audit', label: '审计记录', icon: ClipboardCheck },
    ],
  },
]

const activePath = computed(() => `/${String(route.path.split('/')[1] || 'dashboard')}`)
const activeItem = computed(() => navGroups.flatMap((group) => group.items).find((item) => item.path === activePath.value))
const tenantShort = computed(() => {
  const tenantId = auth.user?.tenant_id || 'default'
  return tenantId === 'default' ? 'default' : tenantId.slice(0, 8)
})

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
        <section v-for="group in navGroups" :key="group.label" class="nav-group">
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

      <el-dropdown trigger="click" placement="top-start" @command="(command: string) => command === 'logout' && logout()">
        <button class="account-entry" type="button">
          <div class="account-avatar">{{ auth.displayName.slice(0, 1).toUpperCase() }}</div>
          <div>
            <strong>{{ auth.displayName }}</strong>
            <span>租户 {{ tenantShort }}</span>
          </div>
          <ChevronUp class="account-chevron" :size="16" />
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout">
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
          <strong>{{ activeItem?.label || '首页工作台' }}</strong>
          <span>当前工作空间：默认项目 · 租户 {{ auth.user?.tenant_id || 'default' }}</span>
        </div>
        <div class="topbar-actions">
          <el-input class="global-search" placeholder="搜索智能体、知识库、运行记录">
            <template #prefix>
              <Search :size="18" />
            </template>
          </el-input>
        </div>
      </header>

      <RouterView />
    </section>
  </main>
</template>
