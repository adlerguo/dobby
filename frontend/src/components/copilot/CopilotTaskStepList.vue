<script setup lang="ts">
defineProps<{
  items?: Record<string, unknown>[]
}>()
</script>

<template>
  <div class="copilot-task-steps">
    <div v-for="(item, index) in items || []" :key="index" class="copilot-task-step">
      <span class="copilot-task-step__index">{{ index + 1 }}</span>
      <div>
        <strong>{{ item.label || item.title }}</strong>
        <small>{{ item.value || item.status || item.description }}</small>
      </div>
    </div>
  </div>
</template>
