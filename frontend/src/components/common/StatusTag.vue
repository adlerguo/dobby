<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  status: string | boolean | null | undefined
  label?: string
}>()

const normalized = computed(() => {
  if (typeof props.status === 'boolean') return props.status ? 'success' : 'danger'
  return String(props.status || 'neutral').toLowerCase()
})

const semantic = computed(() => {
  const value = normalized.value
  if (['success', 'ok', 'active', 'enabled', 'healthy', 'published', 'available', 'verified_local', 'done', 'completed', 'ready', '已连接', '可用', '启用'].includes(value)) {
    return 'success'
  }
  if (['running', 'processing', 'connecting', 'parsing', 'info', '连接中', '解析中', '运行中'].includes(value)) {
    return 'info'
  }
  if (['warning', 'pending', 'draft_required', 'unpublished', 'needs_real_key', 'demo_only', '待配置', '未发布'].includes(value)) {
    return 'warning'
  }
  if (['danger', 'failed', 'error', 'disabled', 'inactive', '连接失败', '已停用', '停用'].includes(value)) {
    return 'danger'
  }
  return 'neutral'
})

const text = computed(() => {
  if (props.label) return props.label
  const value = normalized.value
  const labels: Record<string, string> = {
    active: '启用',
    disabled: '已停用',
    inactive: '已停用',
    ok: '健康',
    done: '完成',
    completed: '完成',
    ready: '完成',
    pending: '待处理',
    parsing: '解析中',
    running: '运行中',
    failed: '连接失败',
    unknown: '未知',
    published: '已发布',
    unpublished: '未发布',
    draft: '草稿',
    verified_local: '可直接体验',
    needs_real_key: '需自备 API Key',
    demo_only: '演示模型（非真实）',
  }
  return labels[value] || String(props.status || '未知')
})

const isLoading = computed(() => semantic.value === 'info')
</script>

<template>
  <span class="ui-status-tag" :class="`ui-status-tag--${semantic}`">
    <span v-if="isLoading" class="ui-status-tag__spinner" />
    {{ text }}
  </span>
</template>
