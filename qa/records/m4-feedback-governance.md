# M4 反馈与治理闭环验收记录

## 范围

本记录覆盖 M4 反馈与治理闭环：正误反馈、错误对话归档、安全评测，以及对话验证页和观测中心的最小联调。

不包含发布版本/回滚、发布前门禁拦截、复杂工单系统、长期记忆、训练/RLHF 或外部安全扫描平台。

## 已实现能力

- 正误反馈：助手消息可提交 positive/negative 反馈，支持原因、备注、meta，反馈关联 message、conversation、agent、trace 和 citations。
- 反馈治理：negative 反馈自动创建 `negative_feedback` incident；反馈可转 eval case；positive 反馈可转 experience。
- 错误归档：新增 incident 服务和 API，支持列表筛选、关闭、忽略、转 eval case；运行时自动归档 fallback、no citation、tool failed、model failed。
- 安全评测：内置 30 条规则评测模板，覆盖 prompt injection、permission、sensitive、tool、grounding 五类；按 agent 运行后输出通过率、风险等级、失败项和建议。
- 前端联调：对话验证页展示反馈控件；观测中心展示问题归档和安全评测入口。

## 数据结构和迁移

新增迁移：

- `backend/alembic/versions/202607310002_feedback_incidents.py`

新增表：

- `message_feedback`
- `conversation_incidents`

`message_feedback` 记录：

- `message_id`
- `conversation_id`
- `agent_id`
- `trace_id`
- `rating`
- `reason`
- `comment`
- `citations`
- `meta`
- `created_by`

`conversation_incidents` 记录：

- `conversation_id`
- `message_id`
- `agent_id`
- `trace_id`
- `incident_type`
- `severity`
- `status`
- `title`
- `detail`
- `resolution_note`
- `created_by/resolved_by/resolved_at`

## 接口清单

- `POST /messages/{message_id}/feedback`
- `GET /feedback`
- `POST /feedback/{feedback_id}/to-eval-case`
- `POST /feedback/{feedback_id}/to-experience`
- `GET /incidents`
- `PATCH /incidents/{incident_id}`
- `POST /incidents/{incident_id}/to-eval-case`
- `GET /security-evals/templates`
- `POST /agents/{agent_id}/security-eval`

## 验收用例

- assistant message 可提交 positive/negative feedback。
- user message 不允许提交反馈。
- negative feedback 自动创建 `negative_feedback` incident。
- feedback 可转 eval case。
- positive feedback 可转 experience。
- 自动归档 fallback_applied、no_citation、tool_failed、model_failed。
- 同一 `trace_id + incident_type` 不重复创建。
- incident 可 resolved/ignored。
- incident 可转 eval case。
- 安全评测模板不少于 30 条，覆盖 5 类。
- 安全评测输出 risk_level、failed_cases、suggestions。
- 安全评测失败项自动创建 `security_eval_failed` incident。

## 验证命令

- `python -m compileall backend/app`
- `python -m py_compile backend/tests/test_message_feedback.py backend/tests/test_incident_service.py backend/tests/test_security_eval.py`
- `python -m py_compile backend/tests/test_eval_semantic.py backend/tests/test_public_agents_stream.py backend/tests/test_agent_path_smoke.py backend/tests/test_audit_permissions.py`
- `python -m py_compile backend/alembic/versions/202607310002_feedback_incidents.py`
- `git diff --check`
- `cd frontend && npm run build`

当前本机 Python 环境缺少 `pytest`，`cd backend && python -m pytest ...` 未能执行，需要在完整后端测试环境补跑。

## 已知限制

- 安全评测是规则评估，不是 LLM judge。
- 发布门禁未实现，留到 M5。
- 错误归档自动创建失败不会影响主对话。
- 当前没有复杂工单流转，只支持 open/resolved/ignored。
- high_latency 和 low_eval_score 自动归档只保留服务扩展位置，本次 MVP 重点覆盖 fallback、工具失败、模型失败、无引用和负反馈。
- 安全评测运行会真实调用 agent，对模型服务和当前 agent 配置有依赖。

## 后续建议

- 在完整依赖环境补跑 M4 pytest 和接口级测试。
- M5 发布前门禁应复用 `security_eval` 报告和 incident 状态，但不应在 M4 阶段拦截发布。
- 后续可在观测中心增加反馈统计、Top 失败原因趋势和 incident 详情抽屉。
