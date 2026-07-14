<script setup lang="ts">
import { CheckCircle2, Database, MessageSquareText, PlugZap, UploadCloud } from 'lucide-vue-next'

import PageHeader from '../components/common/PageHeader.vue'
import StatusTag from '../components/common/StatusTag.vue'

const steps = [
  {
    title: '配置模型 API 并测试连通',
    desc: '先接入真实对话模型和 embedding 模型。测试失败不会写入可用渠道，避免假配置进入运行链路。',
    to: '/model-hub',
    action: '去模型中心',
    icon: PlugZap,
  },
  {
    title: '创建知识库',
    desc: '选择已接入的 embedding 模型创建知识库。已有文档后会锁定 embedding 模型，避免旧向量被孤立。',
    to: '/kbs',
    action: '去知识库实验台',
    icon: Database,
  },
  {
    title: '上传示例文档',
    desc: '可使用 examples/docs 下的示例资料，等待文档解析完成后再做命中测试。',
    to: '/kbs',
    action: '上传文档',
    icon: UploadCloud,
  },
  {
    title: '体验问答与引用',
    desc: '创建智能体并绑定知识库，在调试对话中查看真实回答、引用证据和运行轨迹。',
    to: '/chat',
    action: '去调试对话',
    icon: MessageSquareText,
  },
]
</script>

<template>
  <section class="page quickstart-page">
    <PageHeader
      title="快速开始"
      description="按真实交付路径完成：配置模型、创建知识库、上传文档、体验带引用问答。"
    >
      <template #actions>
        <span class="quickstart-doc-path">教程：docs/quickstart.md</span>
      </template>
    </PageHeader>

    <el-alert
      class="quickstart-alert"
      type="warning"
      :closable="false"
      title="默认路径要求配置真实模型 API。mock 仅用于显式演示，不会在生产模式下参与真实路由。"
    />

    <div class="quickstart-grid">
      <article v-for="(step, index) in steps" :key="step.title" class="quickstart-card">
        <div class="quickstart-card__index">{{ index + 1 }}</div>
        <component :is="step.icon" class="quickstart-card__icon" :size="24" />
        <div class="quickstart-card__body">
          <h2>{{ step.title }}</h2>
          <p>{{ step.desc }}</p>
        </div>
        <RouterLink class="el-button el-button--primary quickstart-card__action" :to="step.to">
          {{ step.action }}
        </RouterLink>
      </article>
    </div>

    <article class="panel-card quickstart-demo-note">
      <div>
        <h2>离线演示分支</h2>
        <p>只有使用 <code>SEED_DEMO_MODE=true ./deploy/quickstart.sh</code> 时才会写入演示模型和示例 Agent。演示模型会明确标注为非真实模型。</p>
      </div>
      <StatusTag status="demo_only" label="演示模型（非真实）" />
    </article>

    <article class="panel-card quickstart-checklist">
      <h2>完成后你应该看到</h2>
      <ul>
        <li><CheckCircle2 :size="16" /> 模型中心里真实渠道测试通过。</li>
        <li><CheckCircle2 :size="16" /> 知识库文档状态为完成，并能查看切片。</li>
        <li><CheckCircle2 :size="16" /> 调试对话返回真实答案，且引用卡片可定位来源。</li>
        <li><CheckCircle2 :size="16" /> 观测中心能看到运行记录和 trace 信息。</li>
      </ul>
    </article>
  </section>
</template>

<style scoped>
.quickstart-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.quickstart-alert {
  max-width: 980px;
}

.quickstart-doc-path {
  font-family: var(--font-family-mono);
  color: var(--color-text-secondary);
  background: var(--color-bg-subtle);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: 8px 12px;
}

.quickstart-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
}

.quickstart-card {
  position: relative;
  min-height: 260px;
  padding: var(--space-5);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.quickstart-card__index {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-sidebar-active);
  color: var(--color-brand-secondary);
  font-weight: 700;
}

.quickstart-card__icon {
  color: var(--color-brand-secondary);
}

.quickstart-card__body {
  flex: 1;
}

.quickstart-card h2,
.quickstart-demo-note h2,
.quickstart-checklist h2 {
  margin: 0 0 var(--space-2);
  font-size: 18px;
  font-weight: 600;
}

.quickstart-card p,
.quickstart-demo-note p {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.quickstart-card__action {
  width: fit-content;
}

.quickstart-demo-note {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
}

.quickstart-checklist ul {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: var(--space-3);
}

.quickstart-checklist li {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
}

.quickstart-checklist svg {
  color: var(--color-success);
}

code {
  font-family: var(--font-family-mono);
  background: var(--color-bg-subtle);
  border-radius: var(--radius-sm);
  padding: 2px 6px;
}

@media (max-width: 1200px) {
  .quickstart-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .quickstart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
