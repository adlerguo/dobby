<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { HelpCircle } from 'lucide-vue-next'

import { apiFetch } from '../api/client'
import type { Agent } from '../api/types'
import GuideBrowser from '../components/guide/GuideBrowser.vue'

const router = useRouter()
const qaLoading = ref(false)

async function openGuideQa() {
  qaLoading.value = true
  try {
    const agents = await apiFetch<Agent[]>('/agents')
    const tutorialAgent = agents.find((agent) => agent.name === '使用教程问答')
    router.push(tutorialAgent ? `/chat?agent_id=${tutorialAgent.id}` : '/chat')
  } finally {
    qaLoading.value = false
  }
}
</script>

<template>
  <section class="guide-page">
    <GuideBrowser />
    <el-button class="guide-qa" type="primary" :loading="qaLoading" @click="openGuideQa">
      <HelpCircle :size="18" />
      教程问答
    </el-button>
  </section>
</template>

<style scoped>
.guide-page {
  display: grid;
  gap: var(--space-5);
}

.guide-qa {
  position: fixed;
  right: var(--space-8);
  bottom: var(--space-8);
  z-index: 20;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  box-shadow: var(--shadow-card);
}
</style>
