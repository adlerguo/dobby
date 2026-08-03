<script setup lang="ts">
import type { CopilotAction, CopilotCard } from '../../types/copilot'
import CopilotTaskStepList from './CopilotTaskStepList.vue'

defineProps<{ card: CopilotCard }>()
const emit = defineEmits<{ action: [action: CopilotAction] }>()
</script>

<template>
  <section class="copilot-card copilot-task-progress-card">
    <header class="copilot-card__header">
      <div>
        <strong>{{ card.title }}</strong>
        <small v-if="card.description">{{ card.description }}</small>
      </div>
    </header>
    <CopilotTaskStepList :items="card.items" />
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
