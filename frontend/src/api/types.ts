export interface TokenOut {
  access_token: string
  token_type: string
  expires_in: number
}

export interface CurrentUser {
  user_id: string
  tenant_id: string
  username: string
  display_name: string
  roles: string[]
  permissions: string[]
}

export interface Agent {
  id: string
  tenant_id?: string
  name: string
  type: string
  status: string
  template_id?: string | null
  persona?: string
  config?: Record<string, unknown>
  model_id?: string | null
  kb_ids?: string[]
  tool_ids?: string[]
}

export interface AgentRagConfig {
  top_k: number
  score_threshold: number
  match_type: 'hybrid' | 'vector' | 'keyword'
}

export interface AgentTemplate {
  id: string
  name: string
  type: string
  persona?: string
  default_config?: Record<string, unknown>
}

export interface Model {
  id: string
  name: string
  type: string
  provider?: string
  status?: string
}

export interface ModelChannelCreate {
  base_url: string
  api_key: string
  weight?: number
  rpm_limit?: number | null
  status?: string
}

export interface ModelChannel {
  id: string
  tenant_id?: string | null
  model_id?: string | null
  base_url: string
  weight?: number | null
  rpm_limit?: number | null
  status?: string | null
  health?: string | null
  created_at?: string | null
}

export interface ModelHub {
  id: string
  name: string
  provider?: string | null
  type: string
  display_name?: string | null
  description?: string | null
  is_active?: boolean | null
  provider_config?: Record<string, unknown>
  import_source?: string | null
  model_icon_path?: string | null
  publish_date?: string | null
  scope_type?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface ModelHubCreate {
  name: string
  provider?: string | null
  type: string
  display_name?: string | null
  description?: string | null
  default_channel?: ModelChannelCreate | null
}

export interface ModelHubUpdate {
  name?: string
  provider?: string | null
  type?: string
  display_name?: string | null
  description?: string | null
  is_active?: boolean
}

export interface ModelCatalog {
  id: string
  provider: string
  model_code: string
  display_name: string
  model_type: 'llm' | 'embedding' | 'rerank' | string
  description?: string | null
  context_window?: number | null
  supports_streaming: boolean
  supports_tools: boolean
  supports_vision: boolean
  default_base_url: string
  protocol: string
  recommended_parameters: Record<string, unknown>
  official_url?: string | null
  pricing: Record<string, unknown>
  icon?: string | null
  sort_order: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ModelCenterConnectRequest {
  runtime_name: string
  api_key: string
  base_url?: string | null
  weight?: number
  test_after_create?: boolean
}

export interface ModelCenterTestResult {
  ok: boolean
  health: string
  error?: string | null
}

export interface ModelCenterConnectResponse {
  model: ModelHub
  channel: ModelChannel
  test_result: ModelCenterTestResult
}

export interface ModelCenterChannelTestResponse {
  channel: ModelChannel
  test_result: ModelCenterTestResult
}

export interface KnowledgeBase {
  id: string
  name: string
  type: string
  status?: string
  description?: string | null
  embedding_model?: string
  created_at?: string
}

export interface RetrieveChunk {
  id?: string
  chunk_id?: string
  doc_id?: string
  doc_name?: string
  document_name?: string
  content?: string
  snippet?: string
  score?: number | null
  vector_score?: number | null
  text_score?: number | null
  meta?: Record<string, unknown>
}

export interface Citation {
  chunk_id?: string
  doc_id?: string
  doc_name?: string
  score?: number | null
  snippet?: string
}

export interface RetrieveOut {
  chunks: RetrieveChunk[]
  citations: Citation[]
}

export interface Tool {
  id: string
  name: string
  type: string
  status?: string
}

export interface Workspace {
  id: string
  name: string
  resources: unknown[]
  created_at?: string
}

export interface AuditLog {
  id: string
  action: string
  resource_type?: string
  resource_id?: string
  detail?: Record<string, unknown>
  created_at?: string
}

export interface DashboardMetric {
  label: string
  value: string | number
  unit?: string
}

export interface PublishedApp {
  id: string
  tenant_id: string
  agent_id: string
  name: string
  status: 'published' | 'unpublished' | string
  publish_type: 'api' | string
  config: Record<string, unknown>
  created_by?: string | null
  created_at: string
  updated_at: string
}

export interface AppApiKey {
  id: string
  tenant_id: string
  app_id: string
  name: string
  key_prefix: string
  scopes: string[]
  status: 'active' | 'disabled' | string
  expires_at?: string | null
  created_by?: string | null
  created_at: string
  last_used_at?: string | null
}

export interface AppApiKeyCreated extends AppApiKey {
  api_key: string
}
