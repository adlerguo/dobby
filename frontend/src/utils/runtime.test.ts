import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClientError, apiFetch } from '../api/client'
import { formatKbError, parseSseEvent } from './runtime'

describe('前端运行工具', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('登录过期时清理本地登录态并跳转登录页', async () => {
    const store = new Map<string, string>([
      ['access_token', 'expired'],
      ['current_user', '{}'],
    ])
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) || '',
      setItem: (key: string, value: string) => store.set(key, value),
      removeItem: (key: string) => store.delete(key),
    })
    vi.stubGlobal('window', { location: { pathname: '/dashboard', href: '' } })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 401, ok: false }))

    await expect(apiFetch('/agents')).rejects.toThrow('登录已失效，请重新登录')
    expect(store.has('access_token')).toBe(false)
    expect(store.has('current_user')).toBe(false)
    expect(window.location.href).toBe('/login')
  })

  it('解析 SSE 事件名和 JSON 数据', () => {
    const event = parseSseEvent('event: delta\ndata: {"text":"你好"}')
    expect(event).toEqual({ event: 'delta', data: { text: '你好' } })
  })

  it('知识库上传失败展示友好提示', () => {
    const message = formatKbError(new ApiClientError({ code: 'unsupported_document_type', message: 'unsupported_document_type' }))
    expect(message).toContain('暂不支持该文件类型')
  })
})
