export interface ApiErrorPayload {
  detail?: string | { code?: string; summary?: string }
  message?: string
}

export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

type JsonBody = Record<string, unknown> | unknown[]
type ApiRequestInit = Omit<RequestInit, 'body'> & { body?: BodyInit | JsonBody }

function getToken() {
  return localStorage.getItem('access_token') || ''
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
    throw new Error('登录已失效，请重新登录')
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => ({} as ApiErrorPayload))
    const detail = payload.detail
    if (detail && typeof detail === 'object') {
      const code = detail.code || ''
      const summary = detail.summary || ''
      throw new Error(code && summary ? `${code}: ${summary}` : code || summary || `请求失败：${response.status}`)
    }
    throw new Error(detail || payload.message || `请求失败：${response.status}`)
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
