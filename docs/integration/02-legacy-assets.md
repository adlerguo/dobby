# 迁移资产清单

说明：用户描述旧工程位于 `./legacy`，但当前仓库实际目录为根目录下 `backend/`、`maas/`、`sandbox/`、`frontend/`。本清单按实际路径分析。

## 总表

| 模块 | 结论 | 理由 | 证据 |
|---|---|---|---|
| `eval_service` 与 `EvalCase/EvalRun` | 保留迁移 | wanwu 目前有统计、模型体验、应用记录，但未发现面向智能体的测试用例、批量运行、断言、通过率评测闭环。 | `backend/app/services/eval_service.py`、`backend/app/models/entities.py`；wanwu 统计在 `wanwu/internal/bff-service/service/statistic_*.go` |
| `Experience` 经验库 | 保留迁移 | wanwu 有 Skill、知识库和 WGA workspace，但未发现“评测通过样本沉淀为经验并按 agent/scene 检索”的同等能力。 | `backend/app/models/entities.py`、`backend/app/services/eval_service.py`；wanwu Skill/工作区在 `wanwu/internal/bff-service/service/skill_workspace*.go` |
| `Experiment` 表 | 部分借鉴 | 旧工程只有表结构，未见成熟服务逻辑；概念可用于 A/B 或评测实验，但不应原样迁移。 | `backend/app/models/entities.py` |
| `dashboard_service` 双视图 | 保留迁移 | wanwu 有 app/model/api-key/client 统计，但 cockpit 的技术视图/管理视图、trace 详情和业务摘要更贴近驾驶舱目标。 | `backend/app/services/dashboard_service.py`；wanwu 统计服务 `wanwu/internal/bff-service/service/statistic_*.go` |
| `tool_service` 的 `nl2data` | 保留迁移 | wanwu 的本体智能体可覆盖结构化数据推理，但旧 `nl2data` 是轻量 demo SQL/SQLite 链路，可作为 cockpit 评测样例和问数基准；生产能力应逐步对接 wanwu 本体。 | `backend/app/services/tool_service.py`；本体服务 `wanwu/docker-compose.ontology.yaml` |
| `rag/` 检索链路 | 丢弃由 wanwu 替代 | wanwu 已有知识库、RAG Python 服务、ES/MinIO/Kafka 文档解析链路，能力强于旧工程 pgvector 简单混合检索。 | `backend/app/rag/retrieve.py`、`backend/app/rag/ingest.py`；`wanwu/internal/knowledge-service/*`、`wanwu/docker-compose.yaml` |
| `maas` 模型网关 | 丢弃由 wanwu 替代 | wanwu model-service 已提供模型导入、OpenAI-compatible 配置、模型体验和统计；旧 maas 只是简单渠道权重、缓存、RPM 与 OpenAI 代理。 | `maas/app/api/openai.py`、`maas/app/services.py`；`wanwu/internal/model-service/*`、`wanwu/internal/bff-service/service/model*.go` |
| `sandbox` 执行器 | 丢弃由 wanwu 替代 | wanwu 已内置 workflow code runner 与 wga-sandbox，且有共享卷、Skill 沙箱和 OpenCode/GUI 能力；旧 sandbox 只允许 Python/命令白名单。 | `sandbox/app/api/exec.py`；`wanwu/docker-compose.yaml`、`wanwu/pkg/wga-sandbox/*` |
| RBAC | 丢弃由 wanwu 替代 | wanwu IAM 已有用户、组织、角色、权限、登录注册，BFF/前端均接入权限点。 | `backend/app/services/rbac_service.py`；`wanwu/proto/iam-service/iam-service.proto`、`wanwu/internal/iam-service/client/model/*.go` |
| workspace | 部分借鉴 | wanwu 有 Skill workspace/WGA workspace，但旧 workspace 的“驾驶舱资源集合：kb/agent/tool/model + layout”可作为 cockpit 产品形态借鉴，不迁移为底座权限/资源管理。 | `backend/app/services/workspace_service.py`、`backend/app/models/entities.py`；`wanwu/internal/bff-service/service/skill_workspace*.go`、`wanwu/pkg/wga-persistent/README.md` |

## 详细判断

### eval_service / EvalCase / EvalRun

保留迁移。

旧工程提供测试用例 CRUD、批量运行智能体、断言类型 `contains/not_contains/always_pass`、score/pass_rate 报告，并可将通过样本写入 Experience。核心代码在 `backend/app/services/eval_service.py`，表结构在 `backend/app/models/entities.py` 的 `EvalCase`、`EvalRun`。wanwu 当前能创建/运行智能体，但没有等价的评测数据模型和断言执行层。

### Experience 经验库

保留迁移。

`Experience` 支持 `agent_id`、`scene`、`content`、`embedding`、`meta`，并在评测通过后自动写入，见 `backend/app/models/entities.py` 与 `backend/app/services/eval_service.py`。wanwu 有知识库和 Skill，但语义是平台资源，不是评测驱动的 agent 经验沉淀。

### Experiment

部分借鉴。

`Experiment` 仅有 `name/type/config/metrics/status` 表结构，未看到配套 service 或 API，见 `backend/app/models/entities.py`。建议后续 cockpit 重新设计为评测批次/策略实验，不直接搬表。

### dashboard_service 双视图

保留迁移。

旧 `dashboard_service` 同时输出 technical/executive 两套视图，基于 `RunTrace`、`Conversation`、`Message` 聚合成功率、耗时、token、工具调用、知识引用、问数等指标，见 `backend/app/services/dashboard_service.py`。wanwu 的统计模块偏调用统计，驾驶舱仍需要这层业务化解释。

### tool_service 的 nl2data

保留迁移。

旧 `nl2data` 有 SQL 生成、只读 SQLite 执行、SELECT 校验、CSV 和摘要输出，见 `backend/app/services/tool_service.py`。wanwu 本体智能体更强，但它是完整结构化推理平台；cockpit 评测阶段仍需要一个确定性、低成本的问数基准工具。

### rag 检索链路

丢弃由 wanwu 替代。

旧链路是文档上传、解析、chunk、embedding、pgvector + FTS 混合召回，见 `backend/app/rag/ingest.py`、`backend/app/rag/retrieve.py`。wanwu 已有知识库服务、RAG 服务、MinIO/Kafka/ES、文档状态回调和知识库权限，见 `wanwu/internal/knowledge-service/*` 与 `wanwu/docker-compose.yaml`，应直接复用底座。

### maas 模型网关

丢弃由 wanwu 替代。

旧 `maas` 提供 OpenAI-compatible `/v1/chat/completions`、`/v1/embeddings`，带渠道权重、缓存、RPM 和用量记录，见 `maas/app/api/openai.py`、`maas/app/services.py`。wanwu 的 model-service/BFF 模型管理已覆盖模型导入、供应商适配、体验、统计和 OpenAI-compatible 配置。

### sandbox 执行器

丢弃由 wanwu 替代。

旧 `sandbox` 只执行 Python 或白名单命令，见 `sandbox/app/api/exec.py`。wanwu 有 `wga-sandbox`、workflow code runner、Skill 工作区与共享数据卷，见 `wanwu/docker-compose.yaml` 与 `wanwu/pkg/wga-sandbox/*`，能力更完整。

### RBAC

丢弃由 wanwu 替代。

旧 RBAC 初始化租户、角色、权限和默认 admin，见 `backend/app/services/rbac_service.py`。wanwu IAM 已提供用户、组织、角色、权限、登录注册、OAuth 应用等 gRPC 接口，见 `wanwu/proto/iam-service/iam-service.proto` 和 `wanwu/internal/iam-service/client/model/*.go`。cockpit 只保存 wanwu 身份映射，不再维护独立 RBAC。

### workspace

部分借鉴。

旧 workspace 可绑定 `kb/agent/tool/model` 并保存 `layout`，见 `backend/app/services/workspace_service.py` 和 `backend/app/models/entities.py`。wanwu 已有 Skill workspace 和 WGA workspace，但 cockpit 的“驾驶舱资源编排视图”仍可借鉴旧模型；不建议作为通用资源权限系统迁移。

