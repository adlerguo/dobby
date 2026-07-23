<script setup lang="ts">
import { Connection, Monitor, Platform, Switch } from '@element-plus/icons-vue'
import { onMounted, ref } from 'vue'

import { getBackendHealth, type HealthOut } from '../api/health'

const health = ref<HealthOut | null>(null)
const health_error = ref('')

onMounted(async () => {
  try {
    health.value = await getBackendHealth()
  } catch {
    health_error.value = '服务状态暂不可用'
  }
})
</script>

<template>
  <main class="page-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">AI</div>
        <div>
          <strong>企业智能体中台</strong>
          <span>AI SaaS Console</span>
        </div>
      </div>

      <nav class="nav-list" aria-label="主导航">
        <a class="nav-item active" href="/">
          <el-icon><Monitor /></el-icon>
          工作台
        </a>
        <a class="nav-item" href="/">
          <el-icon><Platform /></el-icon>
          知识库
        </a>
        <a class="nav-item" href="/">
          <el-icon><Switch /></el-icon>
          智能体
        </a>
        <a class="nav-item" href="/">
          <el-icon><Connection /></el-icon>
          驾驶舱
        </a>
      </nav>
    </aside>

    <section class="content">
      <header class="topbar">
        <h1>平台概览</h1>
        <el-tag v-if="health" type="success" effect="plain">{{ health.service }} {{ health.status }}</el-tag>
        <el-tag v-else-if="health_error" type="danger" effect="plain">{{ health_error }}</el-tag>
        <el-tag v-else effect="plain">检查中</el-tag>
      </header>

      <section class="status-grid">
        <article class="status-card">
          <span>平台服务</span>
          <strong>{{ health?.version ?? '等待连接' }}</strong>
        </article>
        <article class="status-card">
          <span>模型服务</span>
          <strong>8100</strong>
        </article>
        <article class="status-card">
          <span>工具执行</span>
          <strong>8200</strong>
        </article>
        <article class="status-card">
          <span>前端应用</span>
          <strong>Vue3</strong>
        </article>
      </section>
    </section>
  </main>
</template>

<style scoped>
.page-shell {
  display: grid;
  min-height: 100vh;
  grid-template-columns: 260px 1fr;
}

.sidebar {
  border-right: 1px solid #d8dee8;
  background: #ffffff;
  padding: 24px 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border-radius: 8px;
  background: #143d59;
  color: #ffffff;
  font-weight: 700;
}

.brand strong,
.brand span {
  display: block;
}

.brand span {
  margin-top: 3px;
  color: #6b7280;
  font-size: 13px;
}

.nav-list {
  display: grid;
  gap: 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  border-radius: 8px;
  padding: 0 12px;
  color: #475569;
  text-decoration: none;
}

.nav-item.active {
  background: #eaf2f8;
  color: #143d59;
}

.content {
  padding: 28px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.topbar h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.status-card {
  min-height: 112px;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #ffffff;
  padding: 18px;
}

.status-card span,
.status-card strong {
  display: block;
}

.status-card span {
  color: #64748b;
  font-size: 14px;
}

.status-card strong {
  margin-top: 16px;
  color: #111827;
  font-size: 22px;
}

@media (max-width: 860px) {
  .page-shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    border-right: 0;
    border-bottom: 1px solid #d8dee8;
  }

  .nav-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 520px) {
  .content {
    padding: 20px 16px;
  }

  .topbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .status-grid,
  .nav-list {
    grid-template-columns: 1fr;
  }
}
</style>
