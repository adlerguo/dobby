# cockpit-service 集成蓝图

## 1. 服务地图

服务与端口以 `wanwu/docker-compose.yaml`、`wanwu/docker-compose.ontology.yaml` 和各服务 `configs/config.yaml` 为准。

| 服务 | 职责 | 端口 | 依赖/存储 | 证据 |
|---|---:|---:|---|---|
| nginx | 前端入口与反向代理 | 8081 | 代理 BFF、workflow、MinIO、channel、本体 | `wanwu/configs/middleware/nginx/conf.d/aibase.conf` |
| bff-service | Web/API 聚合层、鉴权、业务路由、回调入口 | 6668 | Redis、MinIO、iam/model/mcp/app/knowledge/rag/assistant/operate/agent/channel/workflow | `wanwu/docker-compose.yaml`、`wanwu/internal/bff-service/config/config.go` |
| iam-service | 用户、组织、角色、权限、登录注册 | 8888 | MySQL、Redis | `wanwu/proto/iam-service/iam-service.proto`、`wanwu/internal/iam-service/client/model/*.go` |
| model-service | 模型供应商、模型导入、模型体验 | 8989 | MySQL、Redis | `wanwu/internal/model-service/client/model/*.go`、`wanwu/internal/bff-service/service/model*.go` |
| mcp-service | MCP、内置/自定义工具、Skill 资源 | 9898 | MySQL、Redis | `wanwu/proto/mcp-service/mcp-service.proto`、`wanwu/internal/mcp-service/client/model/*.go` |
| knowledge-service | 知识库元数据、文档任务、权限、标签、QA | 8889 | MySQL、Redis、MinIO、Kafka、rag-wanwu | `wanwu/internal/knowledge-service/client/model/*.go`、`wanwu/configs/microservice/knowledge-service/configs/config.yaml` |
| rag-service | RAG 应用元数据和发布 | 9640 | MySQL、Redis | `wanwu/proto/rag-service/rag-service.proto`、`wanwu/internal/rag-service/client/model/rag.go` |
| rag-wanwu | Python RAG 解析、向量/全文/图谱检索能力 | 8613/8681/10891/15000 | MinIO、Kafka、ES、Redis、BFF 回调 | `wanwu/docker-compose.yaml` |
| assistant-service | 智能体配置、会话、SSE gRPC 流、ES 会话检索 | 8890 | MySQL、Redis、ES、MinIO、agent-service | `wanwu/proto/assistant-service/assistant-service.proto`、`wanwu/internal/assistant-service/client/model/*.go` |
| agent-service | 通用智能体/多智能体运行时 HTTP 接口 | 8990 | MinIO、assistant-service、RAG、BFF | `wanwu/internal/agent-service/server/http/router/agent.go`、`wanwu/configs/microservice/agent-service/configs/config.yaml` |
| operate-service | 运营配置、客户端记录 | 9797 | MySQL | `wanwu/internal/operate-service/client/model/*.go` |
| app-service | 应用空间、API Key、应用会话与统计 | 9988 | MySQL、Redis、MinIO | `wanwu/proto/app-service/app-service.proto`、`wanwu/internal/app-service/client/model/*.go` |
| channel-service | 外部渠道接入 | 9990 | MySQL、Redis、BFF | `wanwu/internal/channel-service/client/model/channel.go`、`wanwu/configs/microservice/channel-service/configs/config.yaml` |
| callback | Python 回调与文件生成/解析适配 | 8669 | Redis、MinIO、rag-wanwu、BFF | `wanwu/docker-compose.yaml`、`wanwu/callback/` |
| workflow | 工作流运行与 OpenAPI | 8998/8999 | MySQL、Redis、MinIO、BFF、agent-service、rag-wanwu、callback | `wanwu/docker-compose.yaml` |
| wga-sandbox | 通用智能体沙箱 | 4096/4097/8080 | 共享卷、Skill 目录 | `wanwu/docker-compose.yaml`、`wanwu/pkg/wga-sandbox/*` |
| 本体服务组 | 本体智能体、数据连接、查询、建模 | 8090/8097/8098/8099/130xx | MySQL、Kafka、ES、Redis | `wanwu/docker-compose.ontology.yaml` |

中间件：

- MySQL：初始化 schema 包括 `iam_service`、`model_service`、`app_service`、`rag_service`、`assistant_service`、`knowledge_service`、`mcp_service`、`operate_service`、`channel_service`、`opencoze`，证据 `wanwu/configs/middleware/mysql/initdb.d/init.sql`。
- Redis、MinIO、Kafka、ES：均在 `wanwu/docker-compose.yaml` 中定义健康检查和环境变量。

## 2. 鉴权机制

BFF JWT 签发与校验：

- signing key 来源：`WANWU_BFF_JWT_SIGNING_KEY` 注入容器环境变量 `JWT_SIGNING_KEY`，证据 `wanwu/docker-compose.yaml`。
- BFF 启动时 `jwt_util.InitUserJWT(config.Cfg().JWT.SigningKey)` 初始化 HMAC 密钥，证据 `wanwu/cmd/bff-service/main.go`。
- token 使用 HS256，claims 只有 `userId`、`bufferTime` 和标准 claims；issuer=`wanwu`、subject=`user`，证据 `wanwu/pkg/jwt-util/jwt.go`。
- 登录流程：BFF 调 IAM `Login`，再用 `jwt_util.GenerateToken(resp.User.GetUserId(), UserTokenTimeout)` 生成 token；登录响应额外返回组织和权限列表，证据 `wanwu/internal/bff-service/service/login.go`。
- 校验流程：BFF middleware 从 `Authorization: Bearer <token>` 取 token，校验 subject，临近过期时通过响应头 `new-token` 续签，证据 `wanwu/internal/bff-service/server/http/middleware/jwt_user.go`。
- 前端请求会带 `Authorization`、`x-user-id`、`x-org-id`、`x-client-id`，证据 `wanwu/web/src/utils/request.js`。
- 前端路由权限来自 `access_cert.user.permission.orgPermission`，证据 `wanwu/web/src/router/permission.js`。

Python FastAPI 新服务校验用户身份的方案：

1. 推荐：由 BFF 或 nginx 作为唯一入口，转发到 cockpit-service 时附带 `x-user-id`、`x-org-id`、`x-client-id`，cockpit-service 只信任内网/BFF 来源。优点是最小改动、与现有前端请求头一致；缺点是必须确保 cockpit-service 不暴露公网直连。
2. 共享 JWT 密钥，自行在 FastAPI 中校验 HS256 token，再要求前端/BFF 传 `x-org-id`。优点是独立；缺点是共享密钥扩大泄漏面，且 JWT 不携带 org/role，仍需额外补组织权限。
3. 调 IAM gRPC：FastAPI 校验 token 后，用 userId 调 `GetUserInfo`/`GetUserPermission`。优点是权限实时；缺点是 Python 需引入 proto/gRPC 客户端，接入成本最高。

推荐方案：阶段 1 采用“BFF/nginx 转发用户头 + cockpit-service 内网访问控制”，后续如 cockpit 需要开放外部 API，再升级为“JWT 校验 + IAM gRPC 权限查询”。

## 3. 新增微服务注册路径

最小接入 cockpit-service 需要改动：

- `wanwu/docker-compose.yaml`：新增 `cockpit-service`，加入 `wanwu-net`，依赖 BFF/Redis/Postgres 或自有 Postgres，暴露内网端口如 `18080`。
- `wanwu/configs/middleware/nginx/conf.d/aibase.conf`：新增 `location ^~ /cockpit/api/ { proxy_pass http://cockpit-service:18080/; }`。
- `wanwu/internal/bff-service/server/http/handler/router/v1/router.go`：如果走 BFF 聚合，需要新增 `registerCockpit(apiV1)`。
- `wanwu/internal/bff-service/server/http/handler/router/v1/*.go` 与 `handler/v1/*.go`：增加 BFF handler，复用 `middleware.JWTUser`、`TraceUser` 和 `getUserID/getOrgID`。
- `wanwu/proto/*`、`wanwu/api/proto/*`：仅当 cockpit 需要 Go gRPC 内部服务时新增 proto；如果 cockpit 只作为外部 HTTP 微服务，可不新增 proto。
- `wanwu/web/src/api/*.js`：新增 cockpit API 封装，复用 `utils/request.js` 自动带 token 与用户头。

证据：BFF 路由集中注册在 `wanwu/internal/bff-service/server/http/handler/router/v1/router.go`；nginx 代理入口在 `wanwu/configs/middleware/nginx/conf.d/aibase.conf`；前端 API 请求封装在 `wanwu/web/src/utils/request.js`。

## 4. 前端扩展点

wanwu 前端是 Vue2 + element-ui：

- 路由在 `wanwu/web/src/router/index.js` 的 `constantRoutes` 中定义，一级页面挂在 `/portal` 的 children 下。
- 权限点来自 `wanwu/web/src/router/constants.js` 的 `PERMS`，路由 `meta.perm` 控制可访问性。
- 路由守卫在 `wanwu/web/src/router/permission.js` 中检查 token 和权限。
- API 封装位于 `wanwu/web/src/api/*.js`，统一使用 `wanwu/web/src/utils/request.js`。
- 页面目录按 `wanwu/web/src/views/<module>/index.vue` 组织，组件在本模块 `components/` 下。

新增一级菜单/页面建议：

- 在 `router/constants.js` 增加 `COCKPIT` 权限点。
- 在 `router/index.js` 的 `/portal.children` 添加 `/cockpit` 路由，`component: resolve => require(['@/views/cockpit'], resolve)`，`meta: { perm: [PERMS.COCKPIT] }`。
- 在菜单数据来源处挂入该权限点；如果菜单由后端权限返回，还需在 IAM 权限初始化/角色配置中增加权限。
- 新增 `web/src/api/cockpit.js`，请求路径建议统一为 `/service/api/v1/cockpit/*` 或 nginx 直通 `/cockpit/api/*`，二选一后固定。

## 5. 数据边界

wanwu MySQL 库表入口：

- schema 初始化：`wanwu/configs/middleware/mysql/initdb.d/init.sql`
- Go ORM model：`wanwu/internal/*/client/model/*.go`
- IAM 用户/组织/角色：`wanwu/internal/iam-service/client/model/*.go`
- 知识库：`wanwu/internal/knowledge-service/client/model/*.go`
- 智能体与会话：`wanwu/internal/assistant-service/client/model/*.go`
- 应用与 API Key 统计：`wanwu/internal/app-service/client/model/*.go`
- MCP/Skill/工具：`wanwu/internal/mcp-service/client/model/*.go`

cockpit-service 数据库建议：

- 推荐保留独立 Postgres/pgvector，不共用 wanwu MySQL。
- 理由：旧工程已有 pgvector、评测、经验库和驾驶舱模型；cockpit 是增量微服务，独立库能降低对 wanwu schema 升级的耦合。
- 不推荐直接共用 MySQL：虽然能少一个数据库，但会污染底座库、迁移风险高，且 Experience/RAG 资产依赖向量能力。
- 可共享的只有身份维度：保存 `wanwu_user_id`、`wanwu_org_id`、`wanwu_app_id/assistant_id` 等外键字符串，不跨库强约束。

## 6. 对话与消息流

Assistant SSE 入口：

- BFF 草稿流式接口：`POST /service/api/v1/assistant/stream/draft`，证据 `wanwu/internal/bff-service/server/http/handler/router/v1/assistant.go`。
- BFF 发布态流式接口：handler 注释标注 `POST /assistant/stream`，证据 `wanwu/internal/bff-service/server/http/handler/v1/assistant.go`；具体注册需在发布路由处补查。
- 入参核心字段：`assistantId`、`conversationId`、`fileInfo`、`prompt`、`systemPrompt`、`draft`，证据 `wanwu/proto/assistant-service/assistant-service.proto` 的 `AssistantConversionStreamReq`。
- gRPC 下游：BFF 调 `assistant.AssistantConversionStream` 或 `MultiAssistantConversionStream`，证据 `wanwu/internal/bff-service/service/assistant_chat.go`。
- 前端用 `fetchEventSource` 发送 POST，headers 带 `Authorization`、`X-Client-ID`，每帧 `JSON.parse(e.data)`，证据 `wanwu/web/src/mixins/sseMethod.js`。

agent-service HTTP 接口：

- `POST /agent/chat`：根据 assistant-service 查询智能体配置后运行单智能体。
- `POST /agent/chat/direct`：无状态接收完整参数，workflow 当前通过 `WANWU_AGENT_API_URL: http://agent-service:8990/agent/chat/direct` 调用。
- `POST /multi_agent/chat`：多智能体运行。

证据：`wanwu/internal/agent-service/server/http/router/agent.go`、`wanwu/internal/agent-service/service/single_agent.go`、`wanwu/internal/agent-service/service/multi_agent.go`、`wanwu/docker-compose.yaml`。

cockpit 后续评测建议以“外部调用方”身份优先走 BFF/OpenAPI，而不是直接调 assistant-service gRPC。原因是 BFF 已处理鉴权、会话、统计、SSE 适配和用户上下文。

