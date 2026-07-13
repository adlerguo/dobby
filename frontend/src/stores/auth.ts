import { defineStore } from 'pinia'

import { apiFetch } from '../api/client'
import type { CurrentUser, TokenOut } from '../api/types'

interface AuthState {
  token: string
  user: CurrentUser | null
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: localStorage.getItem('access_token') || '',
    user: JSON.parse(localStorage.getItem('current_user') || 'null') as CurrentUser | null,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    displayName: (state) => state.user?.display_name || state.user?.username || '未登录',
  },
  actions: {
    async login(payload: { tenant_code: string; username: string; password: string }) {
      const token = await apiFetch<TokenOut>('/auth/login', {
        method: 'POST',
        body: payload,
      })
      this.token = token.access_token
      localStorage.setItem('access_token', token.access_token)
      await this.fetchMe()
    },
    async fetchMe() {
      if (!this.token) return
      this.user = await apiFetch<CurrentUser>('/auth/me')
      localStorage.setItem('current_user', JSON.stringify(this.user))
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('access_token')
      localStorage.removeItem('current_user')
    },
  },
})
