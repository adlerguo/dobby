import { nextTick } from 'vue'
import router from '../router'
import type { CopilotPageAction } from '../types/copilot'
import { getCopilotFormAdapter } from './copilotFormAdapters'

type UiCommand = CopilotPageAction['command']

let activeTimer: number | undefined
let activeTarget: HTMLElement | null = null
let activeBubble: HTMLElement | null = null

export async function executeUiCommand(command: UiCommand): Promise<{ ok: boolean; message: string }> {
  if (command.type === 'navigate') {
    await router.push(command.path)
    return { ok: true, message: '已打开目标页面' }
  }

  if (command.type === 'highlight' || command.type === 'scroll_to' || command.type === 'open_dialog') {
    const target = await findCopilotTarget(command.targetId)
    if (!target) return { ok: false, message: `未找到页面元素：${command.targetId}` }
    target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })
    if (command.type === 'highlight' || command.type === 'open_dialog') {
      highlightElement(target, command.label || '请关注这里')
    }
    return { ok: true, message: command.type === 'scroll_to' ? '已定位到目标区域' : '已高亮目标元素' }
  }

  if (command.type === 'switch_tab') {
    return { ok: false, message: '切换标签页将在后续受控执行阶段开放' }
  }

  if (command.type === 'prefill_form') {
    let adapter = getCopilotFormAdapter(command.targetId)
    if (!adapter && command.targetId === 'agent-create-form') {
      await router.push('/agents?tab=create')
      await nextTick()
      await new Promise((resolve) => window.setTimeout(resolve, 160))
      adapter = getCopilotFormAdapter(command.targetId)
    }
    if (!adapter && command.targetId === 'knowledge-create-form') {
      await router.push('/kbs')
      await nextTick()
      await new Promise((resolve) => window.setTimeout(resolve, 160))
      adapter = getCopilotFormAdapter(command.targetId)
    }
    if (!adapter) return { ok: false, message: `当前页面还没有注册表单：${command.targetId}` }
    await adapter.setValues(command.values)
    const valid = adapter.validate ? await adapter.validate() : true
    return { ok: Boolean(valid), message: valid ? '已填写表单，请检查后确认' : '已填写表单，但仍有字段需要人工检查' }
  }

  if (command.type === 'focus_field') {
    const adapter = getCopilotFormAdapter(command.targetId)
    if (!adapter?.focusField) return { ok: false, message: `当前表单不支持定位字段：${command.field}` }
    await adapter.focusField(command.field)
    return { ok: true, message: '已定位到需要处理的字段' }
  }

  return { ok: false, message: '暂不支持该页面命令' }
}

async function findCopilotTarget(targetId: string): Promise<HTMLElement | null> {
  await nextTick()
  await new Promise((resolve) => window.setTimeout(resolve, 80))
  return document.querySelector<HTMLElement>(`[data-copilot-id="${targetId}"]`)
}

function highlightElement(target: HTMLElement, label: string) {
  clearHighlight()
  activeTarget = target
  target.classList.add('copilot-highlight-target')
  activeBubble = document.createElement('div')
  activeBubble.className = 'copilot-highlight-bubble'
  activeBubble.textContent = label
  document.body.appendChild(activeBubble)
  positionBubble(target, activeBubble)
  activeTimer = window.setTimeout(clearHighlight, 3600)
}

function positionBubble(target: HTMLElement, bubble: HTMLElement) {
  const rect = target.getBoundingClientRect()
  bubble.style.left = `${Math.max(16, Math.min(rect.left, window.innerWidth - 260))}px`
  bubble.style.top = `${Math.max(16, rect.top - 42)}px`
}

export function clearHighlight() {
  if (activeTimer) window.clearTimeout(activeTimer)
  activeTimer = undefined
  if (activeTarget) activeTarget.classList.remove('copilot-highlight-target')
  activeTarget = null
  if (activeBubble) activeBubble.remove()
  activeBubble = null
}
