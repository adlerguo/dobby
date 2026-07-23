import { normalizeApiError } from '../api/client'

export interface ParsedSseEvent {
  event: string
  data: any
}

export function parseSseEvent(raw: string): ParsedSseEvent {
  const event: ParsedSseEvent = { event: 'message', data: {} }
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event.event = line.slice(6).trim()
    if (line.startsWith('data:')) {
      try {
        event.data = JSON.parse(line.slice(5).trim())
      } catch {
        event.data = {}
      }
    }
  }
  return event
}

export function formatKbError(error: unknown) {
  const parsed = normalizeApiError(error)
  const map: Record<string, string> = {
    kb_name_exists: '知识库名称已存在',
    document_name_exists: '该知识库中已存在同名文档',
    unsupported_document_type: '暂不支持该文件类型，请上传 txt、md、pdf 或 docx',
    upload_file_too_large: '文件过大，请上传 20MB 以内的文档',
    kb_not_found: '知识库不存在或已归档',
    not_found: '知识库不存在或已归档',
    kb_embedding_model_locked_has_documents: '该知识库已有文档，embedding 模型和维度已锁定。请新建知识库并重新上传文档。',
  }
  return map[parsed.code] || parsed.message
}
