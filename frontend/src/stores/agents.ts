import { defineStore } from 'pinia'

import { apiFetch } from '../api/client'
import type { Agent } from '../api/types'

interface AgentsState {
  agents: Agent[]
  loading: boolean
  loadedAt: string | null
}

export const useAgentsStore = defineStore('agents', {
  state: (): AgentsState => ({
    agents: [],
    loading: false,
    loadedAt: null,
  }),
  actions: {
    async fetchAgents() {
      this.loading = true
      try {
        const rows = await apiFetch<Agent[]>('/agents')
        this.agents = rows
        this.loadedAt = new Date().toISOString()
        return rows
      } finally {
        this.loading = false
      }
    },
    upsertAgent(agent: Agent) {
      const index = this.agents.findIndex((item) => item.id === agent.id)
      if (index >= 0) this.agents.splice(index, 1, agent)
      else this.agents.push(agent)
      this.loadedAt = new Date().toISOString()
    },
    patchAgent(agent: Partial<Agent> & { id: string }) {
      const index = this.agents.findIndex((item) => item.id === agent.id)
      if (index >= 0) this.agents.splice(index, 1, { ...this.agents[index], ...agent })
      this.loadedAt = new Date().toISOString()
    },
    removeAgent(id: string) {
      this.agents = this.agents.filter((agent) => agent.id !== id)
      this.loadedAt = new Date().toISOString()
    },
  },
})
