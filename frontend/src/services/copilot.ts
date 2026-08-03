import { API_BASE, apiFetch, getAccessToken } from '../api/client'
import type { Agent, CopilotTask, CopilotTaskPlan, KnowledgeBase, KnowledgeDocument, Model } from '../api/types'
import type { CopilotCard, CopilotPageContext, CopilotResponse, CopilotTool, CopilotToolExecution } from '../types/copilot'
import { fetchComputerUseStatus, fetchComputerUseTargets } from './computerUse'

export const registeredCopilotTools: CopilotTool[] = [
  { name: 'agents.list', description: '查询当前租户可访问的智能体列表', category: 'agents', permission: ['agent:publish'], riskLevel: 'L1', requiresConfirmation: false, readOnly: true },
  { name: 'agents.get_status', description: '统计智能体状态', category: 'agents', permission: ['agent:publish'], riskLevel: 'L1', requiresConfirmation: false, readOnly: true },
  { name: 'models.list', description: '查询模型列表', category: 'models', permission: [], riskLevel: 'L1', requiresConfirmation: false, readOnly: true },
  { name: 'knowledge_bases.list', description: '查询知识库列表', category: 'knowledge_bases', permission: ['kb:create'], riskLevel: 'L1', requiresConfirmation: false, readOnly: true },
  { name: 'agents.create_draft', description: '创建智能体草稿', category: 'agents', permission: ['agent:publish'], riskLevel: 'L2', requiresConfirmation: true },
  { name: 'knowledge_bases.create', description: '创建空知识库', category: 'knowledge_bases', permission: ['kb:create'], riskLevel: 'L2', requiresConfirmation: true },
  { name: 'agents.change_model', description: '修改智能体绑定模型', category: 'agents', permission: ['agent:publish'], riskLevel: 'L2', requiresConfirmation: true },
  { name: 'agents.bind_knowledge', description: '给智能体绑定知识库', category: 'agents', permission: ['agent:publish'], riskLevel: 'L2', requiresConfirmation: true },
  { name: 'agents.bind_tool', description: '给智能体绑定工具', category: 'agents', permission: ['agent:publish'], riskLevel: 'L2', requiresConfirmation: true },
  { name: 'agents.update_prompt', description: '修改智能体提示词', category: 'agents', permission: ['agent:publish'], riskLevel: 'L2', requiresConfirmation: true },
  { name: 'computer_use.open_session', description: '在白名单目标中启动隔离浏览器只读观察', category: 'computer_use', permission: [], riskLevel: 'L1', requiresConfirmation: true, readOnly: true },
]

export interface DraftAgentPreview {
  name: string
  type: string
  persona: string
  model_id?: string | null
  model_name?: string | null
  kb_ids: string[]
  kb_names: string[]
  config: Record<string, unknown>
}

interface CopilotExecuteResult {
  tool: string
  status: 'success' | 'failed'
  message: string
  target_type?: string
  target_id?: string
  result: Record<string, unknown>
  audit: Record<string, unknown>
}

export async function handleCopilotPrompt(prompt: string, context: CopilotPageContext): Promise<CopilotResponse> {
  const text = prompt.trim()
  const lower = text.toLowerCase()

  if (isTaskPlanningIntent(text)) {
    return buildTaskPlanPreview(text, context)
  }
  if (isComputerUseIntent(text)) {
    return buildComputerUseConsent(text, context)
  }
  if (isFormPrefillIntent(text)) {
    return buildAgentFormPrefill(text)
  }
  if (isKnowledgeBaseCreateIntent(text)) {
    return buildKnowledgeBasePreview(text)
  }
  if (isChangeModelIntent(text)) {
    return buildChangeModelPreview(text)
  }
  if (isBindKnowledgeIntent(text)) {
    return buildBindKnowledgePreview(text)
  }
  if (isCreateDraftIntent(text)) {
    return buildDraftPreview(text)
  }
  if (includesAny(text, ['异常智能体', '异常助手', '异常'])) {
    return queryAgents('error')
  }
  if (includesAny(text, ['智能体列表', '有哪些智能体', '查看智能体', '智能体状态'])) {
    return queryAgents()
  }
  if (includesAny(text, ['模型列表', '有哪些模型', '当前模型', '模型状态'])) {
    return queryModels()
  }
  if (includesAny(text, ['知识库列表', '有哪些知识库', '知识库状态'])) {
    return queryKnowledgeBases()
  }
  if (includesAny(text, ['文档', '资料']) && includesAny(text, ['知识库', '列表', '状态'])) {
    return queryKnowledgeBases()
  }
  if (includesAny(text, ['带我去', '打开', '前往', '跳转'])) {
    const action = matchNavigation(text)
    if (action) {
      return {
        message: `可以，我为你准备了“${action.label}”动作。`,
        cards: [{ kind: 'actions', title: '页面导航', actions: [{ label: action.label, variant: 'primary', command: action.command }] }],
      }
    }
  }
  if (includesAny(text, ['高亮', '在哪', '哪里', '怎么点'])) {
    const action = context.availableActions.find((item) => item.command.type === 'highlight')
    if (action) {
      return {
        message: `我可以直接帮你定位“${action.label}”。`,
        cards: [{ kind: 'actions', title: '页面引导', actions: [{ label: action.label, variant: 'primary', command: action.command }] }],
      }
    }
  }
  if (includesAny(text, ['当前页面', '怎么用', '做什么'])) {
    return explainCurrentPage(context)
  }
  if (lower.includes('tool registry') || text.includes('工具注册')) {
    return {
      message: `本阶段已注册 ${registeredCopilotTools.length} 个副驾工具，其中 L2 写工具 ${registeredCopilotTools.filter((tool) => tool.riskLevel === 'L2').length} 个，全部需要确认。`,
      cards: [{
        kind: 'data',
        title: '已注册工具',
        items: registeredCopilotTools.map((tool) => ({
          name: tool.name,
          risk: tool.riskLevel,
          mode: tool.requiresConfirmation ? '确认后执行' : '只读',
        })),
      }],
    }
  }

  return platformQa(text, context)
}

async function buildComputerUseConsent(prompt: string, context: CopilotPageContext): Promise<CopilotResponse> {
  const status = await fetchComputerUseStatus().catch(() => ({ enabled: false, reason: 'computer_use_status_unavailable', max_session_minutes: 15, max_actions: 20 }))
  if (!status.enabled) {
    return {
      message: '浏览器操作模式当前由管理员关闭。Mira 不会静默启动浏览器。',
      cards: [{
        kind: 'data',
        title: '浏览器操作模式不可用',
        items: [
          { label: '状态', value: '已关闭' },
          { label: '原因', value: status.reason || 'computer_use_disabled' },
        ],
      }],
    }
  }
  const targets = await fetchComputerUseTargets(context.workspaceId).catch(() => [])
  const target = targets.find((item) => prompt.includes(item.name)) || targets[0]
  if (!target) {
    return {
      message: '没有可用的浏览器操作目标。管理员需要先配置目标系统和域名白名单。',
      cards: [{ kind: 'data', title: '未配置白名单目标', items: [{ label: '执行方式', value: 'unsupported' }] }],
    }
  }
  const startUrl = inferComputerUseUrl(prompt, target.allowed_domains[0])
  const operation: CopilotToolExecution = {
    tool: 'computer_use.open_session',
    input: {
      target_id: target.id,
      user_goal: prompt,
      start_url: startUrl,
    },
    preview: {
      target_name: target.name,
      allowed_domains: target.allowed_domains,
      no_write_actions: true,
      max_session_minutes: Math.min(target.max_session_minutes, status.max_session_minutes),
    },
  }
  return {
    message: '该操作暂时没有标准接口。进入前需要你确认授权，本阶段只做只读浏览。',
    cards: [{
      kind: 'computer-use-consent',
      title: '进入浏览器操作模式',
      description: 'Mira 将在隔离浏览器中打开目标页面并观察页面，不执行写操作。',
      items: [
        { label: '目标系统', value: target.name },
        { label: '允许域名', value: target.allowed_domains.join('、') },
        { label: '用户目标', value: prompt },
        { label: '预计动作', value: '打开页面、观察页面、记录摘要' },
        { label: '不会执行', value: '密码、验证码、提交、上传、下载' },
        { label: '最长时间', value: `${Math.min(target.max_session_minutes, status.max_session_minutes)} 分钟` },
      ],
      actions: [
        { label: '取消', event: 'cancel_operation' },
        { label: '进入浏览器操作模式', variant: 'primary', event: 'confirm_computer_use' },
      ],
      payload: operation as unknown as Record<string, unknown>,
    }],
  }
}

export async function createDraftAgent(preview: DraftAgentPreview): Promise<Agent> {
  const result = await executeCopilotTool({
    tool: 'agents.create_draft',
    input: {
      name: preview.name,
      type: preview.type,
      persona: preview.persona,
      model_id: preview.model_id || null,
      kb_ids: preview.kb_ids,
      tool_ids: [],
      config: preview.config,
    },
    preview: preview as unknown as Record<string, unknown>,
  })
  return (result.result.agent || result.result) as Agent
}

export async function executeCopilotTool(operation: CopilotToolExecution): Promise<CopilotExecuteResult> {
  return apiFetch<CopilotExecuteResult>('/copilot/execute', {
    method: 'POST',
    body: {
      tool: operation.tool,
      input: operation.input,
      preview: operation.preview || null,
      confirmed: true,
    },
  })
}

export async function planCopilotTask(goal: string, context: CopilotPageContext): Promise<CopilotTaskPlan> {
  return apiFetch<CopilotTaskPlan>('/copilot/tasks/plan', {
    method: 'POST',
    body: {
      goal,
      workspace_id: context.workspaceId || null,
      conversation_id: null,
    },
  })
}

export async function createCopilotTask(plan: CopilotTaskPlan, context: CopilotPageContext): Promise<CopilotTask> {
  return apiFetch<CopilotTask>('/copilot/tasks', {
    method: 'POST',
    body: {
      plan,
      workspace_id: context.workspaceId || null,
      conversation_id: null,
    },
  })
}

export async function confirmCopilotTask(taskId: string): Promise<CopilotTask> {
  return apiFetch<CopilotTask>(`/copilot/tasks/${taskId}/confirm`, { method: 'POST', body: {} })
}

export async function pauseCopilotTask(taskId: string): Promise<CopilotTask> {
  return apiFetch<CopilotTask>(`/copilot/tasks/${taskId}/pause`, { method: 'POST', body: {} })
}

export async function resumeCopilotTask(taskId: string): Promise<CopilotTask> {
  return apiFetch<CopilotTask>(`/copilot/tasks/${taskId}/resume`, { method: 'POST', body: {} })
}

export async function cancelCopilotTask(taskId: string): Promise<CopilotTask> {
  return apiFetch<CopilotTask>(`/copilot/tasks/${taskId}/cancel`, { method: 'POST', body: {} })
}

export async function retryCopilotTask(taskId: string): Promise<CopilotTask> {
  return apiFetch<CopilotTask>(`/copilot/tasks/${taskId}/retry`, { method: 'POST', body: {} })
}

export async function getCopilotTask(taskId: string): Promise<CopilotTask> {
  return apiFetch<CopilotTask>(`/copilot/tasks/${taskId}`)
}

export async function fetchRecentCopilotTasks(): Promise<CopilotTask[]> {
  return apiFetch<CopilotTask[]>('/copilot/tasks?limit=5')
}

export async function streamCopilotTaskEvents(
  taskId: string,
  lastEventId: number,
  onEvent: (event: { id: number; type: string; data: Record<string, unknown> }) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = new Headers()
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (lastEventId > 0) headers.set('Last-Event-ID', String(lastEventId))
  const response = await fetch(`${API_BASE}/copilot/tasks/${taskId}/events`, { headers, signal })
  if (!response.ok || !response.body) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (!signal?.aborted) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''
    for (const chunk of chunks) {
      const parsed = parseSseChunk(chunk)
      if (parsed) onEvent(parsed)
    }
  }
}

function parseSseChunk(chunk: string): { id: number; type: string; data: Record<string, unknown> } | null {
  const lines = chunk.split('\n')
  const id = Number(lines.find((line) => line.startsWith('id:'))?.slice(3).trim() || 0)
  const type = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
  const dataLine = lines.find((line) => line.startsWith('data:'))?.slice(5).trim() || '{}'
  try {
    return { id, type, data: JSON.parse(dataLine) as Record<string, unknown> }
  } catch {
    return { id, type, data: {} }
  }
}

async function queryAgents(status?: 'error'): Promise<CopilotResponse> {
  const agents = await apiFetch<Agent[]>('/agents')
  const rows = status === 'error'
    ? agents.filter((agent) => ['failed', 'error', 'disabled'].includes(String(agent.status || '')))
    : agents.slice(0, 8)
  const statusCounts = agents.reduce<Record<string, number>>((acc, agent) => {
    const key = String(agent.status || 'unknown')
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
  const title = status === 'error' ? `发现 ${rows.length} 个异常或不可用智能体` : `当前共有 ${agents.length} 个智能体`
  return {
    message: title,
    cards: [{
      kind: 'data',
      title: '智能体查询结果',
      description: `状态分布：${Object.entries(statusCounts).map(([key, count]) => `${key} ${count}`).join('，') || '暂无数据'}`,
      items: rows.map((agent) => ({
        name: agent.name,
        status: agent.status || '-',
        type: agent.type,
        model_id: agent.model_id || '-',
      })),
      actions: [{ label: '查看智能体管理', variant: 'primary', command: { type: 'navigate', path: '/agents' } }],
    }],
  }
}

async function queryModels(): Promise<CopilotResponse> {
  const models = await apiFetch<Model[]>('/models')
  const rows = models.slice(0, 8)
  return {
    message: `当前可见模型 ${models.length} 个。`,
    cards: [{
      kind: 'data',
      title: '模型查询结果',
      items: rows.map((model) => ({
        name: model.name,
        provider: model.provider || '-',
        type: model.type,
      })),
      actions: [{ label: '打开模型中心', variant: 'primary', command: { type: 'navigate', path: '/model-hub' } }],
    }],
  }
}

async function queryKnowledgeBases(): Promise<CopilotResponse> {
  const kbs = await apiFetch<KnowledgeBase[]>('/kbs')
  return {
    message: `当前可见知识库 ${kbs.length} 个。`,
    cards: [{
      kind: 'data',
      title: '知识库查询结果',
      items: kbs.slice(0, 8).map((kb) => ({
        name: kb.name,
        status: kb.status || '-',
        type: kb.type,
        embedding_model: kb.embedding_model || '-',
      })),
      actions: [{ label: '打开知识库实验台', variant: 'primary', command: { type: 'navigate', path: '/kbs' } }],
    }],
  }
}

export async function queryKnowledgeBaseDocuments(kbId: string): Promise<KnowledgeDocument[]> {
  return apiFetch<KnowledgeDocument[]>(`/kbs/${kbId}/documents`)
}

async function buildDraftPreview(prompt: string): Promise<CopilotResponse> {
  const [models, kbs] = await Promise.all([
    apiFetch<Model[]>('/models').catch(() => []),
    apiFetch<KnowledgeBase[]>('/kbs').catch(() => []),
  ])
  const name = inferAgentName(prompt)
  const model = models.find((item) => item.type === 'llm') || models[0]
  const matchedKbs = recommendKnowledgeBases(prompt, kbs)
  const preview: DraftAgentPreview = {
    name,
    type: 'qa',
    persona: `${name}，负责基于企业知识库回答业务问题。回答需要结构清晰，优先引用企业资料；知识不足时明确说明不足。`,
    model_id: model?.id || null,
    model_name: model?.name || null,
    kb_ids: matchedKbs.map((kb) => kb.id),
    kb_names: matchedKbs.map((kb) => kb.name),
    config: {
      temperature: 0.2,
      answer_style_enabled: true,
      rag: { top_k: 3, score_threshold: 0, match_type: 'hybrid' },
      fallback: {
        enabled: true,
        citation_required: false,
        no_citation_message: '当前知识库没有足够依据，请补充资料后再试。',
      },
      suggested_questions: ['请总结这份资料的重点', '这个流程有什么风险点？', '给出可执行的处理建议'],
    },
  }
  const cards: CopilotCard[] = [{
    kind: 'draft-preview',
    title: '即将创建智能体草稿',
    description: '确认后通过 Tool Registry 创建 draft 状态智能体，不会自动发布。',
    items: [
      { label: '名称', value: preview.name },
      { label: '模型', value: preview.model_name || '暂不绑定' },
      { label: '知识库', value: preview.kb_names.join('、') || '暂不绑定' },
      { label: '工具', value: '暂不绑定' },
      { label: '状态', value: '草稿' },
      { label: '风险等级', value: 'L2 · 需确认' },
    ],
    actions: [
      { label: '手动创建', event: 'manual_create_agent' },
      { label: '确认创建', variant: 'primary', event: 'confirm_execute_tool' },
    ],
    payload: {
      tool: 'agents.create_draft',
      input: {
        name: preview.name,
        type: preview.type,
        persona: preview.persona,
        model_id: preview.model_id || null,
        kb_ids: preview.kb_ids,
        tool_ids: [],
        config: preview.config,
      },
      preview,
    },
  }]
  return { message: `我已根据“${prompt}”生成草稿配置，请确认后创建。`, cards }
}

async function buildTaskPlanPreview(prompt: string, context: CopilotPageContext): Promise<CopilotResponse> {
  const plan = await planCopilotTask(prompt, context)
  return {
    message: '我已把目标拆成结构化任务计划。确认后会在后端持久化执行，关闭副驾后任务状态仍可恢复。',
    cards: [{
      kind: 'task-plan',
      title: plan.title,
      description: plan.summary,
      items: [
        { label: '目标', value: plan.goal },
        { label: '步骤数', value: plan.steps.length },
        { label: '风险', value: plan.steps.some((step) => step.riskLevel === 'L3') ? '包含 L3，发布需二次确认' : 'L1/L2，确认计划后执行' },
        { label: '提醒', value: plan.warnings.join('；') || '无' },
        ...plan.steps.map((step) => ({ label: `${step.order}. ${step.title}`, value: `${step.toolName} · ${step.riskLevel}` })),
      ],
      payload: { plan } as unknown as Record<string, unknown>,
      actions: [
        { label: '取消', event: 'cancel_operation' },
        { label: '确认并开始', variant: 'primary', event: 'confirm_task_plan' },
      ],
    }],
  }
}

async function buildKnowledgeBasePreview(prompt: string): Promise<CopilotResponse> {
  const name = inferKnowledgeBaseName(prompt)
  const type = prompt.includes('政策') ? 'policy' : prompt.includes('合规') || prompt.includes('合同') ? 'compliance' : 'doc_regulation'
  const description = `${name}，用于沉淀企业资料并供智能体检索引用。`
  const operation: CopilotToolExecution = {
    tool: 'knowledge_bases.create',
    input: { name, type, description, config: {}, embedding_model: 'mock-embedding' },
    preview: { name, type, description },
  }
  return {
    message: `我已生成“${name}”创建预览。确认后只创建空知识库，不会读取或上传本地文件。`,
    cards: [confirmationCard('即将创建知识库', '创建空知识库', operation, [
      { label: '名称', value: name },
      { label: '类型', value: type },
      { label: '说明', value: description },
      { label: '风险等级', value: 'L2 · 需确认' },
    ])],
  }
}

async function buildChangeModelPreview(prompt: string): Promise<CopilotResponse> {
  const [agents, models] = await Promise.all([apiFetch<Agent[]>('/agents'), apiFetch<Model[]>('/models')])
  const agent = matchByName(agents, inferTargetAgentName(prompt))
  const model = matchByName(models, inferTargetModelName(prompt)) || models.find((item) => prompt.includes(item.name))
  if (!agent || !model) {
    return missingTargetResponse('修改模型需要先明确智能体和目标模型。可以说：修改销售助手模型为 Qwen-Plus。')
  }
  const currentModel = models.find((item) => item.id === agent.model_id)
  const operation: CopilotToolExecution = {
    tool: 'agents.change_model',
    input: { agent_id: agent.id, model_id: model.id },
    preview: { before: { model: currentModel?.name || '未绑定' }, after: { model: model.name } },
  }
  return {
    message: `准备把“${agent.name}”的模型从“${currentModel?.name || '未绑定'}”修改为“${model.name}”。`,
    cards: [confirmationCard('准备修改智能体配置', '修改模型绑定', operation, [
      { label: '目标', value: agent.name },
      { label: '模型', value: `${currentModel?.name || '未绑定'} -> ${model.name}` },
      { label: '保持不变', value: '提示词、知识库、工具' },
      { label: '风险等级', value: 'L2 · 需确认' },
    ])],
  }
}

async function buildBindKnowledgePreview(prompt: string): Promise<CopilotResponse> {
  const [agents, kbs] = await Promise.all([apiFetch<Agent[]>('/agents'), apiFetch<KnowledgeBase[]>('/kbs')])
  const agent = matchByName(agents, inferTargetAgentName(prompt))
  const kb = matchByName(kbs, inferTargetKnowledgeName(prompt)) || kbs.find((item) => prompt.includes(item.name))
  if (!agent || !kb) {
    return missingTargetResponse('绑定知识库需要先明确智能体和知识库。可以说：给合同助手绑定合同知识库。')
  }
  const currentNames = kbs.filter((item) => agent.kb_ids?.includes(item.id)).map((item) => item.name)
  const nextNames = Array.from(new Set([...currentNames, kb.name]))
  const operation: CopilotToolExecution = {
    tool: 'agents.bind_knowledge',
    input: { agent_id: agent.id, kb_ids: [kb.id] },
    preview: { before: { kb_names: currentNames }, after: { kb_names: nextNames } },
  }
  return {
    message: `准备给“${agent.name}”绑定“${kb.name}”。确认后会保留已有知识库并追加绑定。`,
    cards: [confirmationCard('准备绑定知识库', '追加知识库绑定', operation, [
      { label: '目标', value: agent.name },
      { label: '当前知识库', value: currentNames.join('、') || '未绑定' },
      { label: '新增知识库', value: kb.name },
      { label: '风险等级', value: 'L2 · 需确认' },
    ])],
  }
}

function buildAgentFormPrefill(prompt: string): CopilotResponse {
  const name = inferAgentName(prompt)
  const values = {
    name,
    type: 'qa',
    persona: `${name}，负责基于企业知识库回答业务问题。回答需要结构清晰，优先引用企业资料；知识不足时明确说明不足。`,
  }
  return {
    message: '我可以打开创建向导并填写基础信息。请检查后再由你提交创建。',
    cards: [{
      kind: 'actions',
      title: '自动填写创建向导',
      description: '通过页面 Form Adapter 填写，不会模拟鼠标或直接提交。',
      actions: [
        { label: '打开并填写', variant: 'primary', command: { type: 'prefill_form', targetId: 'agent-create-form', values } },
        { label: '打开创建页', command: { type: 'navigate', path: '/agents?tab=create' } },
      ],
    }],
  }
}

function confirmationCard(title: string, description: string, operation: CopilotToolExecution, items: Record<string, unknown>[]): CopilotCard {
  return {
    kind: 'confirmation',
    title,
    description,
    items,
    payload: operation as unknown as Record<string, unknown>,
    actions: [
      { label: '取消', event: 'cancel_operation' },
      { label: '确认执行', variant: 'primary', event: 'confirm_execute_tool' },
    ],
  }
}

function missingTargetResponse(message: string): CopilotResponse {
  return {
    message,
    cards: [{
      kind: 'actions',
      title: '可以先查看资源',
      actions: [
        { label: '查看智能体', command: { type: 'navigate', path: '/agents' } },
        { label: '查看模型', command: { type: 'navigate', path: '/model-hub' } },
        { label: '查看知识库', command: { type: 'navigate', path: '/kbs' } },
      ],
    }],
  }
}

function explainCurrentPage(context: CopilotPageContext): CopilotResponse {
  return {
    message: `${context.pageTitle}：${context.description || '这是 Mira 工作台中的一个业务页面。'}`,
    cards: [{
      kind: 'actions',
      title: '你可以继续',
      actions: context.availableActions.slice(0, 4).map((action) => ({
        label: action.label,
        command: action.command,
        variant: action.id.includes('create') ? 'primary' : 'secondary',
      })),
    }],
  }
}

function platformQa(prompt: string, context: CopilotPageContext): CopilotResponse {
  const answer = [
    'Mira 的基本工作流是：先接入模型，再创建知识库并上传资料，然后创建智能体绑定模型和知识库，最后在对话验证中测试回答效果并发布。',
    '本阶段我可以回答平台教程问题、查询模型/智能体/知识库、导航页面、高亮关键入口，并在确认后执行受控平台操作。',
    '删除、发布、批量修改、自动上传本地文件等高风险能力不会在本阶段开放。',
  ].join('\n')
  return {
    message: prompt ? answer : `你好，我可以基于当前页面“${context.pageTitle}”帮你查询、导航和创建智能体草稿。`,
    cards: [{
      kind: 'actions',
      title: '推荐操作',
      actions: [
        { label: '打开模型中心', command: { type: 'navigate', path: '/model-hub' } },
        { label: '打开知识库实验台', command: { type: 'navigate', path: '/kbs' } },
        { label: '创建智能体', variant: 'primary', command: { type: 'navigate', path: '/agents?tab=create' } },
      ],
    }],
  }
}

function matchNavigation(text: string) {
  const routes = [
    { keywords: ['模型'], label: '打开模型中心', path: '/model-hub' },
    { keywords: ['知识库', '资料'], label: '打开知识库实验台', path: '/kbs' },
    { keywords: ['智能体工厂', '工厂'], label: '打开智能体工厂', path: '/factory' },
    { keywords: ['智能体管理', '创建智能体'], label: '打开智能体管理', path: '/agents?tab=create' },
    { keywords: ['模板'], label: '打开模板广场', path: '/templates' },
    { keywords: ['对话', '验证'], label: '打开对话验证', path: '/chat' },
    { keywords: ['发布'], label: '打开发布中心', path: '/publish' },
    { keywords: ['观测', '日志', '运行'], label: '打开观测中心', path: '/observability' },
  ]
  const hit = routes.find((route) => route.keywords.some((keyword) => text.includes(keyword)))
  return hit ? { label: hit.label, command: { type: 'navigate' as const, path: hit.path } } : null
}

function isCreateDraftIntent(text: string) {
  return includesAny(text, ['创建', '新建', '帮我做']) && includesAny(text, ['助手', '智能体'])
}

function isKnowledgeBaseCreateIntent(text: string) {
  return includesAny(text, ['创建', '新建']) && includesAny(text, ['知识库', '资料库'])
}

function isChangeModelIntent(text: string) {
  return includesAny(text, ['修改', '换成', '改成', '切换']) && includesAny(text, ['模型'])
}

function isBindKnowledgeIntent(text: string) {
  return includesAny(text, ['绑定', '关联', '接入']) && includesAny(text, ['知识库', '资料库'])
}

function isFormPrefillIntent(text: string) {
  return includesAny(text, ['带我创建', '打开创建', '填写']) && includesAny(text, ['智能体', '助手'])
}

function isTaskPlanningIntent(text: string) {
  const hasMultiStepVerb = includesAny(text, ['并', '然后', '等', '检查', '测试', '发布', '继续上次'])
  const hasPlatformGoal = includesAny(text, ['智能体', '助手', '知识库', '发布'])
  return hasMultiStepVerb && hasPlatformGoal
}

function isComputerUseIntent(text: string) {
  return includesAny(text, ['浏览器操作模式', '旧系统', '第三方系统', '内部系统', '没有接口', '白名单系统'])
}

function inferComputerUseUrl(prompt: string, fallbackDomain?: string) {
  const match = prompt.match(/https?:\/\/[^\s，。]+/)
  if (match?.[0]) return match[0]
  return fallbackDomain ? `https://${fallbackDomain}` : ''
}

function inferAgentName(prompt: string) {
  const match = prompt.match(/(?:创建|新建|生成|做)(?:一个|一名|个)?(.{2,18}?)(?:智能体|助手)/)
  const raw = match?.[1]?.replace(/[，。,.！!？?]/g, '').trim()
  if (raw) return raw.endsWith('助手') ? raw : `${raw}助手`
  if (prompt.includes('合同')) return '合同审查助手'
  if (prompt.includes('客服')) return '客服助手'
  if (prompt.includes('销售')) return '销售助手'
  return '业务问答助手'
}

function inferKnowledgeBaseName(prompt: string) {
  const match = prompt.match(/(?:创建|新建)(?:一个|一套|个)?(.{2,18}?)(?:知识库|资料库)/)
  const raw = match?.[1]?.replace(/[，。,.！!？?]/g, '').trim()
  if (raw) return raw.endsWith('库') ? raw : `${raw}知识库`
  if (prompt.includes('合同')) return '合同知识库'
  if (prompt.includes('政策')) return '政策知识库'
  return '业务知识库'
}

function inferTargetAgentName(prompt: string) {
  const match = prompt.match(/(?:给|把|修改)?(.{2,18}?)(?:智能体|助手)/)
  const raw = match?.[1]?.replace(/[，。,.！!？?]/g, '').trim()
  if (raw) return raw.endsWith('助手') ? raw : `${raw}助手`
  return ''
}

function inferTargetModelName(prompt: string) {
  const match = prompt.match(/(?:模型)?(?:为|到|换成|改成)\s*([A-Za-z0-9_\-+.一-龥]{2,30})/)
  return match?.[1]?.trim() || ''
}

function inferTargetKnowledgeName(prompt: string) {
  const match = prompt.match(/绑定(.{2,18}?)(?:知识库|资料库)/)
  const raw = match?.[1]?.replace(/[，。,.！!？?]/g, '').trim()
  if (raw) return raw.endsWith('库') ? raw : `${raw}知识库`
  return ''
}

function matchByName<T extends { name: string }>(items: T[], name: string) {
  if (!name) return undefined
  return items.find((item) => item.name === name) || items.find((item) => item.name.includes(name) || name.includes(item.name))
}

function recommendKnowledgeBases(prompt: string, kbs: KnowledgeBase[]) {
  if (!kbs.length) return []
  const keywords = prompt.split(/[，。,.！!？?\s]/).filter((item) => item.length >= 2)
  const matched = kbs.filter((kb) => keywords.some((keyword) => kb.name.includes(keyword) || kb.description?.includes(keyword)))
  return (matched.length ? matched : kbs).slice(0, 2)
}

function includesAny(text: string, keywords: string[]) {
  return keywords.some((keyword) => text.includes(keyword))
}
