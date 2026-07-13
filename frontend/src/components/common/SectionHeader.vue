<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <header class="ui-section-header">
    <div class="ui-section-header__copy">
      <h2>{{ title }}</h2>
      <p v-if="description">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="ui-section-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>
