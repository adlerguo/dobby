export interface CopilotFormField {
  name: string
  label: string
  required?: boolean
  sensitive?: boolean
}

export interface CopilotFormAdapter {
  id: string
  getValues: () => Record<string, unknown>
  setValues: (values: Record<string, unknown>) => void | Promise<void>
  validate?: () => boolean | Promise<boolean>
  getFields?: () => CopilotFormField[]
  focusField?: (field: string) => void | Promise<void>
}

const adapters = new Map<string, CopilotFormAdapter>()

export function registerCopilotFormAdapter(adapter: CopilotFormAdapter) {
  adapters.set(adapter.id, adapter)
  return () => unregisterCopilotFormAdapter(adapter.id)
}

export function unregisterCopilotFormAdapter(id: string) {
  adapters.delete(id)
}

export function getCopilotFormAdapter(id: string) {
  return adapters.get(id)
}
