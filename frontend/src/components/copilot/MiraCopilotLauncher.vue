<script setup lang="ts">
import { computed } from 'vue'
import { BotMessageSquare } from 'lucide-vue-next'

import { useCopilotStore } from '../../stores/copilot'

const copilot = useCopilotStore()

const badge = computed(() => {
  const status = copilot.activeTask?.status
  if (!status) return ''
  if (['queued', 'running', 'retrying', 'waiting_external'].includes(status)) return '运行中'
  if (status === 'waiting_confirmation') return '待确认'
  if (status === 'failed') return '失败'
  return ''
})
</script>

<template>
  <button
    v-if="!copilot.isOpen"
    class="mira-copilot-launcher"
    type="button"
    aria-label="打开 Mira 平台副驾"
    @click="copilot.open()"
  >
    <BotMessageSquare :size="24" :stroke-width="1.9" />
    <span>副驾</span>
    <small v-if="badge">{{ badge }}</small>
  </button>
</template>
