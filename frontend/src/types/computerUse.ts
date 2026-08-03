export interface ComputerUseTarget {
  id: string
  tenant_id: string
  workspace_id?: string | null
  name: string
  description?: string | null
  allowed_domains: string[]
  allowed_url_patterns: string[]
  denied_url_patterns: string[]
  allow_navigation: boolean
  allow_form_fill: boolean
  allow_submit: boolean
  allow_upload: boolean
  allow_download: boolean
  allow_login: boolean
  allow_persistent_session: boolean
  max_session_minutes: number
  max_actions: number
  enabled: boolean
  created_by?: string | null
  created_at: string
  updated_at: string
}

export interface ComputerUseSession {
  id: string
  tenant_id: string
  workspace_id?: string | null
  user_id: string
  task_id?: string | null
  conversation_id?: string | null
  target_id: string
  status: 'pending_consent' | 'initializing' | 'running' | 'waiting_user' | 'paused' | 'succeeded' | 'failed' | 'stopped' | 'expired'
  execution_mode: string
  current_url?: string | null
  current_title?: string | null
  allowed_domains: string[]
  user_goal: string
  approved_plan: Record<string, unknown>
  risk_level: string
  started_at?: string | null
  last_activity_at?: string | null
  expires_at?: string | null
  paused_at?: string | null
  completed_at?: string | null
  stopped_at?: string | null
  stop_reason?: string | null
  takeover_required: boolean
  browser_context_ref?: string | null
  security_events: Array<Record<string, unknown>>
  created_at: string
  updated_at: string
}

export interface ComputerUseAction {
  id: string
  session_id: string
  sequence: number
  action_type: string
  target_description?: string | null
  before_url?: string | null
  after_url?: string | null
  before_screenshot_id?: string | null
  after_screenshot_id?: string | null
  status: string
  risk_level: string
  requires_confirmation: boolean
  error_code?: string | null
  error_message?: string | null
  created_at: string
  completed_at?: string | null
}

export interface ComputerUsePageState {
  url: string
  title?: string | null
  summary: string
  interactive_elements: Array<Record<string, unknown>>
  screenshot_id?: string | null
  risk_flags: string[]
}

export interface ComputerUseCaptureResult {
  session: ComputerUseSession
  action: ComputerUseAction
  page_state: ComputerUsePageState
}

export interface ComputerUseStatus {
  enabled: boolean
  reason?: string | null
  max_session_minutes: number
  max_actions: number
}
