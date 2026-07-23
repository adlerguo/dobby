import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    permissions?: string[]
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'quickstart', component: () => import('../views/QuickstartView.vue'), meta: { permissions: ['dashboard:view'] } },
        { path: 'guide', component: () => import('../views/GuideView.vue'), meta: { public: true } },
        { path: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { permissions: ['dashboard:view'] } },
        { path: 'factory', component: () => import('../views/factory/FactoryView.vue'), meta: { permissions: ['agent:publish'] } },
        { path: 'agents', component: () => import('../views/AgentListView.vue'), meta: { permissions: ['agent:publish'] } },
        { path: 'model-hub', component: () => import('../views/ModelHubView.vue'), meta: { permissions: ['maas:admin'] } },
        { path: 'templates', component: () => import('../views/TemplateGalleryView.vue'), meta: { permissions: ['agent:publish'] } },
        { path: 'kbs', component: () => import('../views/KnowledgeBaseListView.vue'), meta: { permissions: ['kb:create'] } },
        { path: 'chat', component: () => import('../views/ChatWorkbenchView.vue'), meta: { permissions: ['dashboard:view'] } },
        { path: 'publish', component: () => import('../views/PublishCenterView.vue'), meta: { permissions: ['agent:publish'] } },
        { path: 'tools', component: () => import('../views/ToolsView.vue'), meta: { permissions: ['agent:publish'] } },
        { path: 'workspaces', component: () => import('../views/WorkspaceView.vue'), meta: { permissions: ['dashboard:view'] } },
        { path: 'observability', component: () => import('../views/ObservabilityCenterView.vue'), meta: { permissions: ['dashboard:view'] } },
        { path: 'audit', component: () => import('../views/AuditLogView.vue'), meta: { permissions: ['audit:view'] } },
        { path: 'admin/users', component: () => import('../views/admin/UserManagementView.vue'), meta: { permissions: ['user:view'] } },
        { path: 'admin/roles', component: () => import('../views/admin/RolePermissionView.vue'), meta: { permissions: ['role:view', 'permission:view'] } },
        { path: 'admin/settings', component: () => import('../views/admin/SystemSettingsView.vue'), meta: { permissions: ['tenant:update'] } },
        { path: '403', component: () => import('../views/ForbiddenView.vue') },
      ],
    },
    {
      path: '/login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
  ],
})

router.beforeEach(async (to) => {
  const token = localStorage.getItem('access_token')
  if (!to.meta.public && !token) {
    return '/login'
  }
  if (to.path === '/login' && token) {
    return '/dashboard'
  }
  if (!to.meta.public && token) {
    const auth = useAuthStore()
    if (!auth.user) {
      await auth.fetchMe().catch(() => auth.logout())
    }
    const permissions = to.meta.permissions || []
    const granted = auth.user?.permissions || []
    if (permissions.length > 0 && !permissions.every((permission) => granted.includes(permission))) {
      return '/403'
    }
  }
  return true
})

export default router
