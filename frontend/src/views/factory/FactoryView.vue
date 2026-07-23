<script setup lang="ts">
import FactoryCanvas from '../../components/factory/FactoryCanvas.vue'
import PageHeader from '../../components/common/PageHeader.vue'
</script>

<template>
  <section class="factory-page">
    <PageHeader title="智能体工厂" description="以工厂视角实时呈现各智能体的运行状态。" />
    <FactoryCanvas />
  </section>
</template>

<style scoped>
.factory-page {
  display: grid;
  gap: var(--space-6);
}
</style>
