export interface ApiErrorPayload {
  detail?: string | { code?: string; summary?: string; message?: string; error?: { code?: string; message?: string } }
  error?: { code?: string; message?: string; detail?: unknown }
  message?: string
}

export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

type JsonBody = Record<string, unknown> | unknown[]
type ApiRequestInit = Omit<RequestInit, 'body'> & { body?: BodyInit | JsonBody }
export type NormalizedApiError = { code: string; message: string }

export class ApiClientError extends Error {
  code: string

  constructor(error: NormalizedApiError) {
    super(error.message)
    this.name = 'ApiClientError'
    this.code = error.code
  }
}

function getToken() {
  return localStorage.getItem('access_token') || ''
}

function normalizePayloadError(payload: ApiErrorPayload, status: number): NormalizedApiError {
  if (payload.error?.code || payload.error?.message) {
    return {
      code: payload.error.code || `http_${status}`,
      message: payload.error.message || payload.error.code || `请求失败：${status}`,
    }
  }

  const detail = payload.detail
  if (typeof detail === 'string') {
    return { code: detail, message: detail }
  }

  if (detail?.error?.code || detail?.error?.message) {
    return {
      code: detail.error.code || `http_${status}`,
      message: detail.error.message || detail.error.code || `请求失败：${status}`,
    }
  }

  if (detail?.code || detail?.summary || detail?.message) {
    return {
      code: detail.code || `http_${status}`,
      message: detail.summary || detail.message || detail.code || `请求失败：${status}`,
    }
  }

  return {
    code: `http_${status}`,
    message: payload.message || `请求失败：${status}`,
  }
}

export function normalizeApiError(error: unknown): NormalizedApiError {
  if (error instanceof ApiClientError) {
    return { code: error.code, message: error.message }
  }
  if (error instanceof Error) {
    return { code: error.message, message: error.message }
  }
  const message = String(error || '请求失败')
  return { code: message, message }
}

export async function apiFetch<T>(path: string, options: ApiRequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {})
  const body = options.body

  if (!(body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const token = getToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    body: body && !(body instanceof FormData) && typeof body !== 'string' ? JSON.stringify(body) : body,
  })

  if (response.status === 401) {
    localStorage.removeItem('access_token')
    localStorage.removeItem('current_user')
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
    throw new ApiClientError({ code: 'unauthorized', message: '登录已失效，请重新登录' })
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => ({} as ApiErrorPayload))
    throw new ApiClientError(normalizePayloadError(payload, response.status))
  }

  if (response.status === 204) {
    return null as T
  }

  return response.json() as Promise<T>
}

export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  return apiFetch<T>(path, {
    method: 'POST',
    body: formData,
    headers: {},
  })
}
