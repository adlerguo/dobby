import { computed } from 'vue'
import { useRoute } from 'vue-router'

import type { CopilotPageContext } from '../types/copilot'

const pageContexts: Record<string, CopilotPageContext> = {
  '/quickstart': {
    routeName: 'quickstart',
    pageTitle: '快速开始',
    description: '从模型接入、知识库构建、智能体创建到问答验证的引导首页。',
    availableActions: [
      { id: 'go-agent-create', label: '开始创建智能体', command: { type: 'navigate', path: '/agents?tab=create' } },
      { id: 'highlight-quickstart-create', label: '高亮创建入口', command: { type: 'highlight', targetId: 'quickstart-create-agent', label: '这里可以开始创建智能体' } },
      { id: 'go-guide', label: '查看完整教程', command: { type: 'navigate', path: '/guide' } },
    ],
    suggestedPrompts: ['这个平台怎么开始使用？', '带我完成第一个智能体', '模型、知识库和智能体是什么关系？'],
  },
  '/factory': {
    routeName: 'factory',
    pageTitle: '智能体工厂',
    description: '以工厂视角查看智能体构建、协作和运行状态。',
    availableActions: [
      { id: 'create-agent', label: '新建智能体', command: { type: 'navigate', path: '/agents?tab=create' } },
      { id: 'highlight-factory-create', label: '高亮新建智能体', command: { type: 'highlight', targetId: 'factory-create-agent', label: '点击这里新建智能体' } },
      { id: 'view-observability', label: '查看运行日志', command: { type: 'navigate', path: '/observability' } },
    ],
    suggestedPrompts: ['当前页面怎么用？', '查看异常智能体', '帮我创建合同审查助手', '分析今日运行数据'],
  },
  '/agents': {
    routeName: 'agents',
    pageTitle: '智能体管理',
    description: '创建、编辑、测试和发布企业智能体。',
    availableActions: [
      { id: 'create-agent', label: '创建智能体', command: { type: 'highlight', targetId: 'agent-create-button', label: '点击这里进入创建向导' } },
      { id: 'template-gallery', label: '打开模板广场', command: { type: 'navigate', path: '/templates' } },
      { id: 'chat-validate', label: '去对话验证', command: { type: 'navigate', path: '/chat' } },
    ],
    suggestedPrompts: ['如何创建一个智能体？', '帮我创建合同审查助手', '查看异常智能体', '带我去模板广场'],
  },
  '/model-hub': {
    routeName: 'model-hub',
    pageTitle: '模型中心',
    description: '接入和管理对话模型、向量模型等模型能力。',
    availableActions: [
      { id: 'highlight-new-model', label: '高亮新建模型', command: { type: 'highlight', targetId: 'model-create-button', label: '这里可以新建模型' } },
      { id: 'go-kbs', label: '前往知识库', command: { type: 'navigate', path: '/kbs' } },
    ],
    suggestedPrompts: ['怎么接入模型？', '列出当前模型', '模型连接失败怎么办？'],
  },
  '/kbs': {
    routeName: 'knowledge-bases',
    pageTitle: '知识库实验台',
    description: '创建知识库、上传文档、检查切片和检索效果。',
    availableActions: [
      { id: 'highlight-create-kb', label: '高亮创建知识库', command: { type: 'highlight', targetId: 'kb-create-button', label: '这里可以创建知识库' } },
      { id: 'highlight-upload-doc', label: '高亮上传文档', command: { type: 'highlight', targetId: 'kb-upload-document', label: '选择知识库后在这里上传文档' } },
    ],
    suggestedPrompts: ['如何创建知识库？', '列出知识库状态', '上传文档后多久可检索？'],
  },
  '/chat': {
    routeName: 'chat',
    pageTitle: '对话验证',
    description: '选择智能体并用真实业务问题验证回答和引用。',
    availableActions: [
      { id: 'highlight-chat-send', label: '高亮发送按钮', command: { type: 'highlight', targetId: 'chat-send-button', label: '输入问题后点击发送' } },
      { id: 'go-agents', label: '返回智能体管理', command: { type: 'navigate', path: '/agents' } },
    ],
    suggestedPrompts: ['这个页面怎么验证智能体？', '为什么没有引用来源？', '带我创建一个可测试的智能体'],
  },
  '/publish': {
    routeName: 'publish',
    pageTitle: '发布中心',
    description: '将智能体发布为外部应用，管理版本、回滚和 API Key。',
    availableActions: [
      { id: 'highlight-publish', label: '高亮发布入口', command: { type: 'highlight', targetId: 'publish-app-button', label: '这里可以发布外部应用' } },
      { id: 'go-agents', label: '选择智能体', command: { type: 'navigate', path: '/agents' } },
    ],
    suggestedPrompts: ['如何发布智能体？', '如何回滚发布版本？', 'API Key 怎么使用？'],
  },
  '/templates': {
    routeName: 'templates',
    pageTitle: '模板广场',
    description: '从预置模板快速创建场景化智能体。',
    availableActions: [
      { id: 'go-agent-create', label: '创建智能体', command: { type: 'navigate', path: '/agents?tab=create' } },
    ],
    suggestedPrompts: ['模板适合哪些场景？', '带我从模板创建智能体', '没有合适模板怎么办？'],
  },
  '/observability': {
    routeName: 'observability',
    pageTitle: '观测中心',
    description: '查看智能体运行、反馈、异常和安全评测状态。',
    availableActions: [
      { id: 'go-factory', label: '回到智能体工厂', command: { type: 'navigate', path: '/factory' } },
    ],
    suggestedPrompts: ['如何分析运行异常？', '今日运行数据怎么样？', '哪里查看安全评测？'],
  },
}

const fallbackContext: CopilotPageContext = {
  routeName: 'workspace',
  pageTitle: 'Mira 工作台',
  description: '企业智能体工作台页面。',
  availableActions: [
    { id: 'go-quickstart', label: '打开快速开始', command: { type: 'navigate', path: '/quickstart' } },
    { id: 'go-factory', label: '打开智能体工厂', command: { type: 'navigate', path: '/factory' } },
  ],
  suggestedPrompts: ['当前页面是做什么的？', '带我去智能体工厂', '如何创建智能体？'],
}

export function resolveCopilotContext(path: string): CopilotPageContext {
  const firstSegment = `/${String(path.split('/')[1] || '')}`
  return pageContexts[firstSegment] || fallbackContext
}

export function useCopilotContext() {
  const route = useRoute()
  const context = computed(() => resolveCopilotContext(route.path))
  return { context }
}

