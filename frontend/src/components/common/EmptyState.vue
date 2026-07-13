<script setup lang="ts">
import { Inbox } from 'lucide-vue-next'

defineProps<{
  title: string
  description: string
  actionText?: string
}>()

const emit = defineEmits<{
  action: []
}>()
</script>

<template>
  <div class="ui-empty-state">
    <div class="ui-empty-state__icon">
      <slot name="icon">
        <Inbox :size="44" :stroke-width="1.7" />
      </slot>
    </div>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
    <el-button v-if="actionText" type="primary" @click="emit('action')">{{ actionText }}</el-button>
  </div>
</template>
