import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'dashboard', component: () => import('../views/DashboardView.vue') },
        { path: 'agents', component: () => import('../views/AgentListView.vue') },
        { path: 'model-hub', component: () => import('../views/ModelHubView.vue') },
        { path: 'templates', component: () => import('../views/TemplateGalleryView.vue') },
        { path: 'kbs', component: () => import('../views/KnowledgeBaseListView.vue') },
        { path: 'chat', component: () => import('../views/ChatWorkbenchView.vue') },
        { path: 'publish', component: () => import('../views/PublishCenterView.vue') },
        { path: 'tools', component: () => import('../views/ToolsView.vue') },
        { path: 'workspaces', component: () => import('../views/WorkspaceView.vue') },
        { path: 'observability', component: () => import('../views/ObservabilityCenterView.vue') },
        { path: 'audit', component: () => import('../views/AuditLogView.vue') },
      ],
    },
    {
      path: '/login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  if (!to.meta.public && !token) {
    return '/login'
  }
  if (to.path === '/login' && token) {
    return '/dashboard'
  }
  return true
})

export default router
