import type { Component } from 'vue'

export type CopilotMode = 'ask' | 'guide' | 'act'
export type CopilotMessageRole = 'user' | 'assistant' | 'system'
export type CopilotCardKind = 'actions' | 'data' | 'task' | 'draft-preview' | 'confirmation' | 'task-plan' | 'task-progress' | 'task-recovery' | 'test-result' | 'preflight' | 'computer-use-consent' | 'computer-use-session'

export interface CopilotToolExecution {
  tool: string
  input: Record<string, unknown>
  preview?: Record<string, unknown>
}

export interface CopilotPageAction {
  id: string
  label: string
  command:
    | { type: 'navigate'; path: string }
    | { type: 'highlight'; targetId: string; label?: string }
    | { type: 'scroll_to'; targetId: string; label?: string }
    | { type: 'switch_tab'; tab: string }
    | { type: 'open_dialog'; targetId: string; label?: string }
    | { type: 'prefill_form'; targetId: string; values: Record<string, unknown> }
    | { type: 'focus_field'; targetId: string; field: string }
}

export interface CopilotPageContext {
  routeName: string
  pageTitle: string
  description?: string
  workspaceId?: string
  selectedEntity?: {
    type: string
    id: string
    name?: string
  }
  availableActions: CopilotPageAction[]
  suggestedPrompts: string[]
}

export interface CopilotAction {
  label: string
  variant?: 'primary' | 'secondary'
  command?: CopilotPageAction['command']
  event?: 'confirm_create_draft' | 'confirm_execute_tool' | 'confirm_task_plan' | 'pause_task' | 'resume_task' | 'cancel_task' | 'retry_task' | 'manual_create_agent' | 'cancel_operation' | 'retry' | 'confirm_computer_use' | 'stop_computer_use'
}

export interface CopilotCard {
  kind: CopilotCardKind
  title: string
  description?: string
  items?: Record<string, unknown>[]
  actions?: CopilotAction[]
  payload?: Record<string, unknown>
}

export interface CopilotMessage {
  id: string
  role: CopilotMessageRole
  content: string
  createdAt: string
  cards?: CopilotCard[]
}

export interface CopilotTool {
  name: string
  description: string
  category: string
  riskLevel: 'L0' | 'L1' | 'L2' | 'L3'
  requiresConfirmation: boolean
  permission: string[]
  inputSchema?: Record<string, unknown>
  readOnly?: boolean
}

export interface CopilotResponse {
  message: string
  cards?: CopilotCard[]
}

export interface CopilotQuickPrompt {
  label: string
  prompt: string
  icon?: Component
}
