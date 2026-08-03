import { defineStore } from 'pinia'

import type { CopilotTask, CopilotTaskPlan } from '../api/types'
import {
  cancelCopilotTask,
  confirmCopilotTask,
  createCopilotTask,
  executeCopilotTool,
  fetchRecentCopilotTasks,
  getCopilotTask,
  handleCopilotPrompt,
  pauseCopilotTask,
  resumeCopilotTask,
  retryCopilotTask,
  streamCopilotTaskEvents,
  type DraftAgentPreview,
} from '../services/copilot'
import {
  captureComputerUseSession,
  createComputerUseSession,
  stopComputerUseSession,
} from '../services/computerUse'
import type { ComputerUseSession } from '../types/computerUse'
import type {
  CopilotAction,
  CopilotCard,
  CopilotMessage,
  CopilotMode,
  CopilotPageContext,
  CopilotToolExecution,
} from '../types/copilot'
import { executeUiCommand } from '../utils/uiCommandBus'

const STORAGE_KEY = 'mira_copilot_open'

function makeMessage(role: CopilotMessage['role'], content: string, cards?: CopilotCard[]): CopilotMessage {
  return {
    id: typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
    role,
    content,
    cards,
    createdAt: new Date().toISOString(),
  }
}

function loadOpenState() {
  if (typeof localStorage === 'undefined') return false
  return localStorage.getItem(STORAGE_KEY) === 'true'
}

function saveOpenState(open: boolean) {
  if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, String(open))
}

export const useCopilotStore = defineStore('copilot', {
  state: () => ({
    isOpen: loadOpenState(),
    mode: 'ask' as CopilotMode,
    loading: false,
    input: '',
    pendingDraft: null as DraftAgentPreview | null,
    pendingOperation: null as CopilotToolExecution | null,
    pendingPlan: null as CopilotTaskPlan | null,
    activeTask: null as CopilotTask | null,
    activeComputerUseSession: null as ComputerUseSession | null,
    activeContext: null as CopilotPageContext | null,
    taskEventCursor: 0,
    taskEventTaskId: null as string | null,
    taskEventController: null as AbortController | null,
    messages: [
      makeMessage('assistant', '你好，我是 Mira 平台副驾。你可以问我当前页面怎么用，也可以让我带你定位入口、确认执行平台操作或启动跨模块任务。'),
    ] as CopilotMessage[],
  }),
  actions: {
    open() {
      this.isOpen = true
      saveOpenState(true)
      void this.restoreLatestTask()
    },
    close() {
      this.isOpen = false
      saveOpenState(false)
    },
    toggle() {
      this.isOpen ? this.close() : this.open()
    },
    setMode(mode: CopilotMode) {
      this.mode = mode
    },
    async sendPrompt(prompt: string, context: CopilotPageContext) {
      const value = prompt.trim()
      if (!value || this.loading) return
      this.open()
      this.activeContext = context
      this.messages.push(makeMessage('user', value))
      this.loading = true
      try {
        const response = await handleCopilotPrompt(value, context)
        const executableCard = response.cards?.find((card) => card.payload && (card.kind === 'draft-preview' || card.kind === 'confirmation'))
        const taskPlanCard = response.cards?.find((card) => card.payload && card.kind === 'task-plan')
        this.pendingOperation = executableCard?.payload ? (executableCard.payload as unknown as CopilotToolExecution) : this.pendingOperation
        this.pendingPlan = taskPlanCard?.payload?.plan ? (taskPlanCard.payload.plan as unknown as CopilotTaskPlan) : this.pendingPlan
        this.pendingDraft = this.pendingOperation?.tool === 'agents.create_draft'
          ? (this.pendingOperation.preview as unknown as DraftAgentPreview)
          : this.pendingDraft
        this.messages.push(makeMessage('assistant', response.message, response.cards))
      } catch (error) {
        const message = error instanceof Error ? error.message : '请求失败，请稍后再试。'
        this.messages.push(makeMessage('assistant', message))
      } finally {
        this.loading = false
      }
    },
    async runAction(action: CopilotAction) {
      if (this.loading) return
      if (action.event === 'confirm_create_draft' || action.event === 'confirm_execute_tool') {
        await this.confirmExecuteTool()
        return
      }
      if (action.event === 'confirm_task_plan') {
        await this.confirmTaskPlan()
        return
      }
      if (action.event === 'confirm_computer_use') {
        await this.confirmComputerUse()
        return
      }
      if (action.event === 'stop_computer_use') {
        await this.stopComputerUse()
        return
      }
      if (action.event === 'pause_task') return this.updateActiveTask('pause')
      if (action.event === 'resume_task') return this.updateActiveTask('resume')
      if (action.event === 'cancel_task') return this.updateActiveTask('cancel')
      if (action.event === 'retry_task') return this.updateActiveTask('retry')
      if (action.event === 'cancel_operation') {
        this.pendingOperation = null
        this.pendingDraft = null
        this.pendingPlan = null
        this.messages.push(makeMessage('assistant', '已取消本次操作，没有修改任何数据。'))
        return
      }
      if (action.event === 'manual_create_agent') {
        await executeUiCommand({ type: 'navigate', path: '/agents?tab=create' })
        this.messages.push(makeMessage('assistant', '已打开智能体创建向导，你可以手动检查并填写配置。'))
        return
      }
      if (!action.command) return
      this.loading = true
      try {
        const result = await executeUiCommand(action.command)
        this.messages.push(makeMessage('assistant', result.message))
      } finally {
        this.loading = false
      }
    },
    async confirmExecuteTool() {
      if (!this.pendingOperation || this.loading) {
        this.messages.push(makeMessage('assistant', '当前没有可确认的操作。'))
        return
      }
      this.loading = true
      try {
        const result = await executeCopilotTool(this.pendingOperation)
        const operation = this.pendingOperation
        const created = (result.result.agent || result.result.knowledge_base || {}) as { id?: string; name?: string }
        const targetName = created.name || '目标资源'
        const targetPath = operation.tool.startsWith('knowledge_bases.') ? '/kbs' : '/agents'
        this.pendingDraft = null
        this.pendingOperation = null
        this.messages.push(makeMessage('assistant', `操作已完成：${targetName}。本次执行已写入审计记录。`, [{
          kind: 'actions',
          title: '下一步',
          actions: [
            { label: operation.tool.startsWith('knowledge_bases.') ? '查看知识库实验台' : '查看智能体管理', variant: 'primary', command: { type: 'navigate', path: targetPath } },
            ...(operation.tool === 'agents.create_draft' && created.id ? [{ label: '去对话验证', command: { type: 'navigate' as const, path: `/chat?agent_id=${created.id}` } }] : []),
          ],
        }]))
      } catch (error) {
        const message = error instanceof Error ? error.message : '操作失败，请检查权限和参数后重试。'
        this.messages.push(makeMessage('assistant', message))
      } finally {
        this.loading = false
      }
    },
    async confirmTaskPlan() {
      if (!this.pendingPlan || this.loading) {
        this.messages.push(makeMessage('assistant', '当前没有可确认的任务计划。'))
        return
      }
      this.loading = true
      try {
        const task = await createCopilotTask(this.pendingPlan, this.activeContext || { routeName: '', pageTitle: '', availableActions: [], suggestedPrompts: [] })
        this.pendingPlan = null
        this.activeTask = await confirmCopilotTask(task.id)
        this.subscribeTaskEvents(this.activeTask.id)
        this.messages.push(makeMessage('assistant', `任务已开始：${this.activeTask.title}`, [taskProgressCard(this.activeTask)]))
      } catch (error) {
        const message = error instanceof Error ? error.message : '任务启动失败，请检查权限或计划参数。'
        this.messages.push(makeMessage('assistant', message))
      } finally {
        this.loading = false
      }
    },
    async confirmComputerUse() {
      if (!this.pendingOperation || this.pendingOperation.tool !== 'computer_use.open_session' || this.loading) {
        this.messages.push(makeMessage('assistant', '当前没有可进入的浏览器操作授权。'))
        return
      }
      this.loading = true
      try {
        const input = this.pendingOperation.input
        const session = await createComputerUseSession({
          target_id: String(input.target_id || ''),
          user_goal: String(input.user_goal || ''),
          start_url: String(input.start_url || ''),
          workspace_id: this.activeContext?.workspaceId || null,
          conversation_id: null,
          approved_plan: this.pendingOperation.preview || {},
          consent_approved: true,
        })
        const capture = await captureComputerUseSession(session.id, {
          current_url: session.current_url || undefined,
          page_title: session.current_title || undefined,
        })
        this.activeComputerUseSession = capture.session
        this.pendingOperation = null
        this.messages.push(makeMessage('assistant', '已进入隔离浏览器只读观察模式。', [computerUseSessionCard(capture.session)]))
      } catch (error) {
        const message = error instanceof Error ? error.message : '浏览器操作模式启动失败。'
        this.messages.push(makeMessage('assistant', message))
      } finally {
        this.loading = false
      }
    },
    async stopComputerUse() {
      if (!this.activeComputerUseSession || this.loading) return
      this.loading = true
      try {
        this.activeComputerUseSession = await stopComputerUseSession(this.activeComputerUseSession.id)
        this.messages.push(makeMessage('assistant', '浏览器操作模式已停止，会话已关闭。', [computerUseSessionCard(this.activeComputerUseSession)]))
      } catch (error) {
        const message = error instanceof Error ? error.message : '停止浏览器操作模式失败。'
        this.messages.push(makeMessage('assistant', message))
      } finally {
        this.loading = false
      }
    },
    async updateActiveTask(action: 'pause' | 'resume' | 'cancel' | 'retry') {
      if (!this.activeTask || this.loading) return
      this.loading = true
      try {
        if (action === 'pause') this.activeTask = await pauseCopilotTask(this.activeTask.id)
        if (action === 'resume') this.activeTask = await resumeCopilotTask(this.activeTask.id)
        if (action === 'cancel') this.activeTask = await cancelCopilotTask(this.activeTask.id)
        if (action === 'retry') this.activeTask = await retryCopilotTask(this.activeTask.id)
        if (['resume', 'retry'].includes(action)) this.subscribeTaskEvents(this.activeTask.id)
        this.messages.push(makeMessage('assistant', `任务状态已更新：${this.activeTask.status}`, [taskProgressCard(this.activeTask)]))
      } catch (error) {
        const message = error instanceof Error ? error.message : '任务操作失败。'
        this.messages.push(makeMessage('assistant', message))
      } finally {
        this.loading = false
      }
    },
    async restoreLatestTask() {
      if (this.activeTask) return
      try {
        const tasks = await fetchRecentCopilotTasks()
        const task = tasks.find((item) => ['queued', 'running', 'retrying', 'waiting_external', 'waiting_confirmation', 'paused', 'failed'].includes(item.status))
        if (!task) return
        this.activeTask = task
        this.subscribeTaskEvents(task.id)
      } catch {
        // Keep drawer usable even if task recovery lookup fails.
      }
    },
    subscribeTaskEvents(taskId: string) {
      this.taskEventController?.abort()
      if (this.taskEventTaskId !== taskId) {
        this.taskEventCursor = 0
        this.taskEventTaskId = taskId
      }
      const controller = new AbortController()
      this.taskEventController = controller
      void streamCopilotTaskEvents(taskId, this.taskEventCursor, async (event) => {
        if (event.id && event.id <= this.taskEventCursor) return
        if (event.id) this.taskEventCursor = event.id
        if (event.type === 'heartbeat') return
        try {
          this.activeTask = await getCopilotTask(taskId)
          this.messages.push(makeMessage('assistant', `任务更新：${this.activeTask.status}`, [taskProgressCard(this.activeTask)]))
        } catch {
          // Ignore transient refresh failures; SSE reconnect or manual open will restore.
        }
      }, controller.signal)
    },
  },
})

function taskProgressCard(task: CopilotTask): CopilotCard {
  const canPause = ['queued', 'running', 'retrying'].includes(task.status)
  const canResume = ['paused', 'waiting_external', 'failed', 'waiting_confirmation'].includes(task.status)
  const canRetry = ['failed', 'partially_succeeded'].includes(task.status)
  return {
    kind: 'task-progress',
    title: task.title,
    description: task.result_summary || `当前状态：${task.status}，进度 ${task.progress_percent}%`,
    items: [
      { label: '任务 ID', value: task.id },
      { label: '状态', value: task.status },
      { label: '进度', value: `${task.progress_percent}%` },
      ...task.steps.map((step) => ({ label: `${step.step_order}. ${step.title}`, value: `${step.status}${step.error_message ? ` · ${step.error_message}` : ''}` })),
    ],
    actions: [
      ...(canPause ? [{ label: '暂停', event: 'pause_task' as const }] : []),
      ...(canResume ? [{ label: '继续', variant: 'primary' as const, event: 'resume_task' as const }] : []),
      ...(canRetry ? [{ label: '重试', variant: 'primary' as const, event: 'retry_task' as const }] : []),
      { label: '取消', event: 'cancel_task' },
    ],
  }
}

function computerUseSessionCard(session: ComputerUseSession): CopilotCard {
  const isActive = ['initializing', 'running', 'paused'].includes(session.status)
  return {
    kind: 'computer-use-session',
    title: '浏览器操作模式',
    description: `状态：${session.status}`,
    items: [
      { label: '目标', value: session.user_goal },
      { label: '当前页面', value: session.current_title || session.current_url || '-' },
      { label: '允许域名', value: session.allowed_domains.join('、') || '-' },
      { label: '模式', value: '只读观察' },
    ],
    payload: session as unknown as Record<string, unknown>,
    actions: isActive ? [{ label: '停止', event: 'stop_computer_use' }] : [],
  }
}
