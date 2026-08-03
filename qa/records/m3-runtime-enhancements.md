# M3 智能体运行时增强验收记录

## 范围

本记录覆盖 M3 智能体运行时增强：意图识别、上下文压缩、异常 fallback，以及智能体配置页和对话验证页的联调检查。

不包含正误反馈、错误对话归档、安全评测、发布版本/回滚、长期记忆或新的复杂流程编排器。

## 已实现能力

- 意图识别：新增 `orchestrator/intent.py`，支持 `kb_qa`、`doc_lookup`、`task_action`、`data_query`、`chit_chat`、`unsupported`、`unsafe`；默认关闭，关闭时返回 `kb_qa` 且不改变现有链路。
- 规则识别：可识别 unsafe、unsupported、task_action、data_query、doc_lookup 和普通知识问答。
- LLM JSON 分类降级：保留 LLM JSON 解析能力和 `llm_classifier` 扩展点；当前运行时未接真实分类模型，`mode=llm` 时会降级到规则识别，不中断主链路。
- 策略处理：unsafe 可阻断，unsupported 可返回边界说明，低置信度可返回澄清问题；结果写入 `ContextBuildOut.intent` 和 trace。
- 上下文压缩：新增 `orchestrator/context_compression.py`，支持 `recent_only`、`summary`、`hybrid`；默认关闭，开启后超过阈值才压缩。
- 摘要降级：摘要生成失败时降级为 `recent_only`，不影响对话继续。
- 异常 fallback：新增 `orchestrator/runtime_fallback.py`，统一处理 `model_error`、`retrieval_empty`、`tool_error`、`policy_blocked`、`unsupported_intent`、`low_confidence` 等场景。
- citation required：当 `fallback.citation_required=true` 且没有 citation 时，直接返回无依据文案，不调用模型编造答案。
- 前端联调：智能体编辑/创建页增加 M3 配置；对话验证页展示 intent、compression、fallback 状态。

## 配置结构

配置复用 `Agent.config`，不新增数据库表。

```json
{
  "intent": {
    "enabled": false,
    "mode": "rule",
    "low_confidence_threshold": 0.55,
    "clarify_on_low_confidence": true,
    "block_unsafe": true
  },
  "context_compression": {
    "enabled": false,
    "strategy": "recent_only",
    "trigger_tokens": 2400,
    "keep_recent": 6,
    "summary_max_tokens": 700
  },
  "fallback": {
    "enabled": true,
    "citation_required": false,
    "no_citation_message": "我没有在已绑定知识库中找到足够依据，暂不能给出确定答案。",
    "tool_error_message": "工具调用失败，请稍后重试或联系管理员。",
    "model_error_message": "模型服务暂时不可用，请稍后重试。",
    "unsupported_message": "这个问题超出当前智能体的能力范围。",
    "unsafe_message": "该请求存在安全风险，无法处理。"
  }
}
```

## 接口和响应字段

`AgentRunIn` 新增可选字段：

- `intent_mode`
- `skip_intent`

`AgentRunOut` 新增字段：

- `intent`
- `fallback_applied`
- `fallback_reason`
- `fallback_message`

`ContextBuildOut` 新增字段：

- `intent`
- `compression_strategy`
- `compression_applied`
- `original_history_tokens`
- `compressed_history_tokens`
- `compressed_message_count`
- `compression_fallback`
- `compression_summary`

流式对话新增事件：

- `fallback`

流式 `done` payload 增加 intent、compression 和 fallback 字段。

## 验收用例

- intent disabled 返回 `kb_qa`，不改变既有回答链路。
- rule 模式能识别 unsafe、unsupported、task_action、kb_qa。
- LLM JSON 解析失败降级到规则识别。
- 低置信度触发澄清策略。
- unsafe block 返回 `policy_blocked` fallback。
- `recent_only` 保留最近消息并记录压缩统计。
- `hybrid` 超过阈值后生成摘要并保留最近消息。
- 摘要失败降级 `recent_only`。
- 空历史不报错。
- `citation_required=true` 且无 citation 时返回 no citation fallback。
- 模型异常返回 `model_error` fallback。
- 工具失败标记 `tool_error` fallback。
- `AgentRunOut` fallback 字段存在。
- 对话验证页能展示 intent、compression、fallback 状态。

## 验证命令

- `python -m compileall backend/app`
- `python -m py_compile backend/tests/test_orchestrator_intent.py backend/tests/test_context_compression.py backend/tests/test_runtime_fallback.py`
- `python -m py_compile backend/tests/test_agent_path_smoke.py backend/tests/test_public_agents_stream.py backend/tests/test_openai_compat.py backend/tests/test_eval_semantic.py`
- `git diff --check`
- `cd frontend && npm run build`

当前本机 Python 环境缺少 `pytest`，`cd backend && python -m pytest ...` 未能执行，需要在完整后端测试环境补跑。

当前 LLM intent 和 summary 未接真实模型服务。运行时 `mode=llm` 会降级到规则识别；摘要使用本地抽取式摘要，真实模型摘要可后续接入。

## 已知限制

- intent 默认关闭，避免改变现有正常对话行为。
- LLM intent 目前只保留 JSON 解析和降级扩展点，没有调用真实分类模型。
- 上下文 summary 目前是轻量抽取式摘要，不是模型生成摘要；摘要失败会降级 `recent_only`。
- fallback 是运行时保护，不替代 M4 的错误归档和反馈闭环。
- tool_error fallback 统一了用户文案和 trace 标记，但没有实现工具重试或备用工具。
- M3 未新增 `conversation_summaries` 表，摘要只进入本次 context/trace，不作为长期记忆持久化。

## 后续建议

- 在完整依赖环境补跑 M3 pytest，并补同步/流式接口级集成测试。
- 用 100 条标注意图集评估规则和 LLM 模式准确率。
- 接入真实 LLM JSON 分类和摘要生成前，先固定 JSON schema、超时和降级策略。
- 进入 M4 时把 fallback 结果接入错误归档和正误反馈闭环。
