import { defineStore } from 'pinia'

export const useAppStore = defineStore('app', {
  state: () => ({
    app_name: '企业 AI 智能体中台',
  }),
})

