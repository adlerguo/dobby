<script setup lang="ts">
import { CheckCircle2 } from 'lucide-vue-next'

import type { CopilotAction, CopilotMessage } from '../../types/copilot'
import CopilotPreflightCard from './CopilotPreflightCard.vue'
import CopilotTaskPlanCard from './CopilotTaskPlanCard.vue'
import CopilotTaskProgressCard from './CopilotTaskProgressCard.vue'
import CopilotTaskRecoveryCard from './CopilotTaskRecoveryCard.vue'
import CopilotTestResultCard from './CopilotTestResultCard.vue'
import ComputerUseConsentCard from './ComputerUseConsentCard.vue'
import ComputerUseSessionCard from './ComputerUseSessionCard.vue'

defineProps<{
  messages: CopilotMessage[]
  loading?: boolean
}>()

const emit = defineEmits<{
  action: [action: CopilotAction]
}>()

function itemEntries(item: Record<string, unknown>) {
  return Object.entries(item).filter(([, value]) => value !== undefined && value !== null && value !== '')
}
</script>

<template>
  <div class="copilot-message-list">
    <article v-for="message in messages" :key="message.id" class="copilot-message" :class="`is-${message.role}`">
      <div class="copilot-message__bubble">
        <p>{{ message.content }}</p>

        <div v-if="message.cards?.length" class="copilot-card-stack">
          <template v-for="card in message.cards" :key="`${message.id}-${card.title}`">
            <CopilotTaskPlanCard v-if="card.kind === 'task-plan'" :card="card" @action="emit('action', $event)" />
            <CopilotTaskProgressCard v-else-if="card.kind === 'task-progress'" :card="card" @action="emit('action', $event)" />
            <CopilotTaskRecoveryCard v-else-if="card.kind === 'task-recovery'" :card="card" @action="emit('action', $event)" />
            <CopilotTestResultCard v-else-if="card.kind === 'test-result'" :card="card" @action="emit('action', $event)" />
            <CopilotPreflightCard v-else-if="card.kind === 'preflight'" :card="card" @action="emit('action', $event)" />
            <ComputerUseConsentCard v-else-if="card.kind === 'computer-use-consent'" :card="card" @action="emit('action', $event)" />
            <ComputerUseSessionCard v-else-if="card.kind === 'computer-use-session'" :card="card" @action="emit('action', $event)" />
          <section v-else class="copilot-card" :class="`card-${card.kind}`">
            <header class="copilot-card__header">
              <span v-if="card.kind === 'draft-preview'" class="copilot-card__status">
                <CheckCircle2 :size="15" />
              </span>
              <div>
                <strong>{{ card.title }}</strong>
                <small v-if="card.description">{{ card.description }}</small>
              </div>
            </header>

            <div v-if="card.items?.length" class="copilot-card__items">
              <div v-for="(item, index) in card.items" :key="index" class="copilot-card__item">
                <template v-if="'label' in item || 'value' in item">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </template>
                <template v-else>
                  <div v-for="[key, value] in itemEntries(item)" :key="key" class="copilot-card__kv">
                    <span>{{ key }}</span>
                    <strong>{{ value }}</strong>
                  </div>
                </template>
              </div>
            </div>

            <div v-if="card.actions?.length" class="copilot-card__actions">
              <button
                v-for="action in card.actions"
                :key="action.label"
                class="copilot-action"
                :class="{ primary: action.variant === 'primary' }"
                type="button"
                @click="emit('action', action)"
              >
                {{ action.label }}
              </button>
            </div>
          </section>
          </template>
        </div>
      </div>
    </article>

    <article v-if="loading" class="copilot-message is-assistant">
      <div class="copilot-message__bubble">
        <span class="copilot-typing">正在处理</span>
      </div>
    </article>
  </div>
</template>
