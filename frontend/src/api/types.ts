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

export interface Tenant {
  id: string
  name: string
  code: string
  status: string
}

export interface PlatformUser {
  id: string
  tenant_id: string
  username: string
  display_name?: string | null
  email?: string | null
  status?: string | null
}

export interface PlatformUserCreate {
  username: string
  password: string
  display_name?: string | null
  email?: string | null
}

export interface PlatformUserUpdate {
  display_name?: string | null
  email?: string | null
  status?: 'active' | 'disabled'
}

export interface Role {
  id: string
  tenant_id: string
  name: string
  code: string
}

export interface Permission {
  id: string
  code: string
  name?: string | null
  module?: string | null
}

export interface AssignRolesOut {
  user_id: string
  role_codes: string[]
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

export interface AgentIntentConfig {
  enabled: boolean
  mode: 'rule' | 'llm'
  low_confidence_threshold: number
  clarify_on_low_confidence: boolean
  block_unsafe: boolean
}

export interface AgentContextCompressionConfig {
  enabled: boolean
  strategy: 'recent_only' | 'summary' | 'hybrid'
  trigger_tokens: number
  keep_recent: number
  summary_max_tokens: number
}

export interface AgentFallbackConfig {
  enabled: boolean
  citation_required: boolean
  no_citation_message: string
  tool_error_message: string
  model_error_message: string
  unsupported_message: string
  unsafe_message: string
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
  model_type: 'llm' | 'embedding' | 'rerank' | 'vision' | 'asr' | 'tts' | 'image' | string
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
  embedding_dim?: number | null
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
  config: Record<string, unknown>
  embedding_model?: string
  embedding_dim?: number
  created_at?: string
  updated_at?: string
}

export interface KnowledgeDocumentWarning {
  code?: string
  message?: string
}

export interface KnowledgeDocumentDuplicateMeta {
  status?: 'none' | 'file_duplicate' | 'text_duplicate' | string
  matched_document_id?: string
  matched_document_name?: string
}

export interface KnowledgeDocumentIngestTaskMeta {
  status?: string
  raw_chars?: number
  cleaned_chars?: number
  raw_lines?: number
  cleaned_lines?: number
  removed_lines?: number
  removed_blank_lines?: number
  removed_noise_lines?: number
  cleaning_version?: string
  text_fingerprint?: string
  chunk_strategy?: string
  chunk_method?: string
  fallback_chunking?: boolean
  chunk_count?: number
  embedding_dim?: number
  error?: unknown
}

export interface DocumentSourceMeta {
  source_name?: string | null
  source_type?: 'upload' | 'api' | 'sync' | 'manual' | string | null
  tags?: string[]
  version_label?: string | null
  published_at?: string | null
  author?: string | null
  publisher?: string | null
  effective_at?: string | null
  expired_at?: string | null
}

export interface KnowledgeDocumentMeta {
  batch_id?: string
  file_sha256?: string
  text_fingerprint?: string
  duplicate?: KnowledgeDocumentDuplicateMeta
  warnings?: KnowledgeDocumentWarning[]
  ingest_task?: KnowledgeDocumentIngestTaskMeta
  source?: DocumentSourceMeta
  [key: string]: unknown
}

export interface KnowledgeDocument {
  id: string
  tenant_id: string
  kb_id: string
  name: string
  source_uri?: string | null
  mime?: string | null
  size?: number | null
  parse_status?: 'pending' | 'parsing' | 'done' | 'failed' | string | null
  meta?: KnowledgeDocumentMeta
  logical_doc_id: string
  version_no: number
  version_status: 'active' | 'inactive' | 'archived' | string
  version_parent_id?: string | null
  activated_at?: string | null
  created_at: string
}

export interface DocumentVersion {
  id: string
  logical_doc_id: string
  version_no: number
  version_status: 'active' | 'inactive' | 'archived' | string
  version_parent_id?: string | null
  name: string
  parse_status?: string | null
  meta?: KnowledgeDocumentMeta
  created_at: string
  activated_at?: string | null
}

export interface DocumentVersionCreateResult {
  document: KnowledgeDocument
  previous_active_id?: string | null
  status: string
  warnings: string[]
}

export type DocumentBatchWarning = string | KnowledgeDocumentWarning

export interface DocumentBatchItem {
  filename: string
  status: 'created' | 'failed'
  document_id?: string | null
  error?: string | null
  warnings: DocumentBatchWarning[]
}

export interface DocumentBatchCreateResult {
  batch_id: string
  total: number
  created: number
  failed: number
  items: DocumentBatchItem[]
}

export interface DocumentBatchStatusItem {
  document_id: string
  name: string
  parse_status?: string | null
  error_code?: string | null
  created_at: string
}

export interface DocumentBatchStatus {
  batch_id: string
  total: number
  document_success: number
  document_failed: number
  document_processing: number
  items: DocumentBatchStatusItem[]
}

export interface KnowledgeChunk {
  id: string
  seq?: number | null
  content: string
  content_length: number
  tokens?: number | null
  meta: Record<string, unknown> & DocumentSourceMeta
  has_embedding: boolean
  page_start?: number | null
  page_end?: number | null
  paragraph_start?: number | null
  paragraph_end?: number | null
  block_start?: number | null
  block_end?: number | null
  created_at: string
}

export interface ReindexOut {
  kb_id: string
  document_count: number
  status: string
}

export interface RetrieveChunk {
  id?: string
  chunk_id?: string
  doc_id?: string
  doc_name?: string
  document_name?: string
  seq?: number | null
  content?: string
  content_length?: number
  snippet?: string
  score?: number | null
  vector_score?: number | null
  text_score?: number | null
  match_channels?: Array<'vector' | 'keyword' | string>
  meta?: Record<string, unknown>
  rerank_mode?: string | null
  rerank_score?: number | null
  rerank_factors?: Record<string, unknown> | null
  rerank_fallback?: boolean | null
  source_name?: string | null
  source_type?: string | null
  tags?: string[]
  version_label?: string | null
  published_at?: string | null
  page_start?: number | null
  page_end?: number | null
  paragraph_start?: number | null
  paragraph_end?: number | null
  block_start?: number | null
  block_end?: number | null
}

export interface Citation {
  chunk_id?: string
  doc_id?: string
  doc_name?: string
  seq?: number | null
  content_length?: number
  score?: number | null
  vector_score?: number | null
  text_score?: number | null
  match_channels?: Array<'vector' | 'keyword' | string>
  snippet?: string
  rerank_mode?: string | null
  rerank_score?: number | null
  rerank_factors?: Record<string, unknown> | null
  rerank_fallback?: boolean | null
  source_name?: string | null
  source_type?: string | null
  tags?: string[]
  version_label?: string | null
  published_at?: string | null
  page_start?: number | null
  page_end?: number | null
  paragraph_start?: number | null
  paragraph_end?: number | null
  block_start?: number | null
  block_end?: number | null
}

export interface RetrieveOut {
  chunks: RetrieveChunk[]
  citations: Citation[]
  rerank_mode?: string | null
  rerank_fallback?: boolean | null
  rerank_latency_ms?: number | null
  rerank_input_count?: number | null
  rerank_output_count?: number | null
}

export interface RuntimeDoneMeta {
  conversation_id?: string
  user_message_id?: string
  assistant_message_id?: string
  trace_id?: string
  usage?: Record<string, unknown>
  tool_results?: unknown[]
  citation_count?: number
  intent?: Record<string, unknown> | null
  fallback_applied?: boolean
  fallback_reason?: string | null
  fallback_message?: string | null
  compression_strategy?: string | null
  compression_applied?: boolean
  original_history_tokens?: number | null
  compressed_history_tokens?: number | null
  compressed_message_count?: number
  compression_fallback?: boolean
  [key: string]: unknown
}

export interface FeedbackOut {
  id: string
  message_id: string
  conversation_id?: string | null
  agent_id?: string | null
  trace_id?: string | null
  rating: string
  reason?: string | null
  comment?: string | null
  created_at: string
}

export interface Incident {
  id: string
  incident_type: string
  severity: string
  status: string
  title: string
  detail: Record<string, unknown>
  agent_id?: string | null
  trace_id?: string | null
  created_at: string
  resolution_note?: string | null
}

export interface SecurityEvalTemplate {
  id: string
  group: string
  title: string
  input: string
  expected_behavior: string
}

export interface SecurityEvalFailedCase {
  id: string
  group: string
  title: string
  input: string
  answer: string
  reason: string
  suggestion: string
  trace_id?: string | null
}

export interface SecurityEvalReport {
  agent_id: string
  total: number
  passed: number
  failed: number
  pass_rate: number
  risk_level: string
  failed_cases: SecurityEvalFailedCase[]
  suggestions: string[]
}

export interface Tool {
  id: string
  tenant_id?: string
  name: string
  type: 'http' | 'code' | 'builtin' | 'mcp' | string
  tool_schema?: Record<string, unknown>
  schema?: Record<string, unknown>
  config?: Record<string, unknown>
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
  active_version_id?: string | null
  active_version_no?: number | null
  created_at: string
  updated_at: string
}

export interface PublishPrecheck {
  status: 'passed' | 'warning' | 'blocked' | string
  checks: Array<{
    check: string
    status: 'passed' | 'warning' | 'blocked' | string
    level: 'block' | 'warning' | string
    message: string
  }>
}

export interface PublishedAppVersionCreate {
  title?: string | null
  release_note?: string | null
  activate?: boolean
  force?: boolean
}

export interface PublishedAppVersion {
  id: string
  tenant_id: string
  app_id: string
  agent_id: string
  version_no: number
  status: 'active' | 'inactive' | string
  title?: string | null
  release_note?: string | null
  snapshot: Record<string, unknown>
  precheck_result: PublishPrecheck | Record<string, unknown>
  created_by?: string | null
  created_at: string
  activated_at?: string | null
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

export interface CopilotTaskPlanStep {
  clientStepId: string
  order: number
  title: string
  description: string
  toolName: string
  toolArguments: Record<string, unknown>
  dependencies: string[]
  riskLevel: 'L1' | 'L2' | 'L3'
  requiresConfirmation: boolean
  waitCondition?: Record<string, unknown> | null
}

export interface CopilotTaskPlan {
  title: string
  goal: string
  summary: string
  steps: CopilotTaskPlanStep[]
  warnings: string[]
}

export interface CopilotTaskStep {
  id: string
  task_id: string
  step_order: number
  client_step_id?: string | null
  title: string
  description?: string | null
  tool_name: string
  tool_arguments: Record<string, unknown>
  dependencies: string[]
  wait_condition?: Record<string, unknown> | null
  risk_level: string
  requires_confirmation: boolean
  status: string
  retry_count: number
  max_retries: number
  idempotency_key: string
  output?: Record<string, unknown> | null
  error_code?: string | null
  error_message?: string | null
  claimed_by?: string | null
  claimed_at?: string | null
  lease_expires_at?: string | null
  heartbeat_at?: string | null
  execution_attempt: number
  next_retry_at?: string | null
  next_check_at?: string | null
  check_interval_seconds: number
  timeout_at?: string | null
  last_observed_status?: string | null
  check_count: number
  started_at?: string | null
  completed_at?: string | null
  created_at: string
  updated_at: string
}

export interface CopilotTask {
  id: string
  tenant_id: string
  workspace_id?: string | null
  user_id: string
  conversation_id?: string | null
  title: string
  user_goal: string
  plan_version: number
  status: string
  current_step_id?: string | null
  progress_percent: number
  plan: Record<string, unknown>
  warnings: string[]
  result_summary?: string | null
  error_code?: string | null
  error_message?: string | null
  started_at?: string | null
  completed_at?: string | null
  cancelled_at?: string | null
  cancellation_reason?: string | null
  created_at: string
  updated_at: string
  steps: CopilotTaskStep[]
}
