<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Bot, Minus, Send, X } from 'lucide-vue-next'

import { useCopilotContext } from '../../composables/useCopilotContext'
import { useCopilotStore } from '../../stores/copilot'
import type { CopilotAction, CopilotMode } from '../../types/copilot'
import CopilotMessageList from './CopilotMessageList.vue'

const copilot = useCopilotStore()
const { context } = useCopilotContext()
const messageBox = ref<HTMLElement | null>(null)

const modeTabs: Array<{ value: CopilotMode; label: string }> = [
  { value: 'ask', label: '问我' },
  { value: 'guide', label: '带我做' },
  { value: 'act', label: '帮我做' },
]

const placeholder = computed(() => {
  if (copilot.mode === 'guide') return '输入你想定位或学习的操作'
  if (copilot.mode === 'act') return '例如：帮我创建合同审查助手'
  return '输入你想问 Mira 的问题'
})

watch(
  () => copilot.messages.length,
  async () => {
    await nextTick()
    messageBox.value?.scrollTo({ top: messageBox.value.scrollHeight, behavior: 'smooth' })
  },
)

async function send() {
  const value = copilot.input
  copilot.input = ''
  await copilot.sendPrompt(value, context.value)
}

function submitOnEnter(event: KeyboardEvent) {
  if (event.shiftKey) return
  event.preventDefault()
  send()
}

function runQuickPrompt(prompt: string) {
  copilot.input = prompt
  send()
}

function runAction(action: CopilotAction) {
  copilot.runAction(action)
}
</script>

<template>
  <Teleport to="body">
    <div v-if="copilot.isOpen" class="mira-copilot-shell">
      <button class="mira-copilot-backdrop" type="button" aria-label="关闭副驾" @click="copilot.close()" />
      <aside class="mira-copilot-panel" aria-label="Mira 平台副驾">
        <header class="copilot-panel__header">
          <div class="copilot-title">
            <span class="copilot-title__icon">
              <Bot :size="22" :stroke-width="1.9" />
            </span>
            <div>
              <strong>Mira 平台副驾</strong>
              <small>当前页面：{{ context.pageTitle }}</small>
            </div>
          </div>
          <div class="copilot-window-actions">
            <button type="button" aria-label="收起副驾" @click="copilot.close()">
              <Minus :size="18" />
            </button>
            <button type="button" aria-label="关闭副驾" @click="copilot.close()">
              <X :size="18" />
            </button>
          </div>
        </header>

        <div class="copilot-mode-tabs" role="tablist" aria-label="副驾模式">
          <button
            v-for="tab in modeTabs"
            :key="tab.value"
            type="button"
            :class="{ active: copilot.mode === tab.value }"
            @click="copilot.setMode(tab.value)"
          >
            {{ tab.label }}
          </button>
        </div>

        <section class="copilot-suggestions" aria-label="推荐问题">
          <button
            v-for="prompt in context.suggestedPrompts"
            :key="prompt"
            type="button"
            @click="runQuickPrompt(prompt)"
          >
            {{ prompt }}
          </button>
        </section>

        <section ref="messageBox" class="copilot-messages">
          <CopilotMessageList :messages="copilot.messages" :loading="copilot.loading" @action="runAction" />
        </section>

        <footer class="copilot-composer">
          <button class="composer-plus" type="button" aria-label="添加上下文">+</button>
          <textarea
            v-model="copilot.input"
            :placeholder="placeholder"
            rows="1"
            @keydown.enter="submitOnEnter"
          />
          <button class="composer-send" type="button" :disabled="copilot.loading || !copilot.input.trim()" @click="send">
            <Send :size="17" :stroke-width="2" />
            <span>发送</span>
          </button>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>
