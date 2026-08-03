<script setup lang="ts">
import { ShieldCheck } from 'lucide-vue-next'

import type { CopilotAction, CopilotCard } from '../../types/copilot'

defineProps<{ card: CopilotCard }>()
const emit = defineEmits<{ action: [action: CopilotAction] }>()
</script>

<template>
  <section class="copilot-card computer-use-card">
    <header class="copilot-card__header">
      <span class="copilot-card__status computer-use-card__icon">
        <ShieldCheck :size="16" />
      </span>
      <div>
        <strong>{{ card.title }}</strong>
        <small v-if="card.description">{{ card.description }}</small>
      </div>
    </header>
    <div class="computer-use-card__notice">只读浏览，不填写、不提交、不下载。</div>
    <div v-if="card.items?.length" class="copilot-card__items">
      <div v-for="(item, index) in card.items" :key="index" class="copilot-card__item">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
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
