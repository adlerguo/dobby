import { apiFetch } from '../api/client'
import type {
  ComputerUseCaptureResult,
  ComputerUseSession,
  ComputerUseStatus,
  ComputerUseTarget,
} from '../types/computerUse'

export async function fetchComputerUseStatus(): Promise<ComputerUseStatus> {
  return apiFetch<ComputerUseStatus>('/computer-use/status')
}

export async function fetchComputerUseTargets(workspaceId?: string): Promise<ComputerUseTarget[]> {
  const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}&enabled_only=true` : '?enabled_only=true'
  return apiFetch<ComputerUseTarget[]>(`/computer-use/targets${query}`)
}

export async function createComputerUseSession(input: {
  target_id: string
  user_goal: string
  start_url: string
  workspace_id?: string | null
  conversation_id?: string | null
  approved_plan?: Record<string, unknown>
  consent_approved: boolean
}): Promise<ComputerUseSession> {
  return apiFetch<ComputerUseSession>('/computer-use/sessions', {
    method: 'POST',
    body: input,
  })
}

export async function captureComputerUseSession(
  sessionId: string,
  input: { current_url?: string | null; page_title?: string | null; visible_text?: string | null },
): Promise<ComputerUseCaptureResult> {
  return apiFetch<ComputerUseCaptureResult>(`/computer-use/sessions/${sessionId}/capture`, {
    method: 'POST',
    body: input,
  })
}

export async function stopComputerUseSession(sessionId: string): Promise<ComputerUseSession> {
  return apiFetch<ComputerUseSession>(`/computer-use/sessions/${sessionId}/stop`, {
    method: 'POST',
    body: {},
  })
}
