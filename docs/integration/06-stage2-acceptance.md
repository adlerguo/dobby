# 阶段 2 验收记录

## 范围

阶段 2 将 legacy 评测体系与 Experience 经验库迁入 `cockpit-service`，评测对象改为 wanwu assistant。

## 已完成

- 新增 SSE 契约探针：`cockpit/scripts/probe_assistant_stream.py`
- 新增契约文件：`cockpit/app/contracts/assistant_stream_contract.json`
- 新增 SSE 解析器：`cockpit/app/services/sse_contract.py`
- 新增评测模型：
  - `eval_cases`
  - `eval_runs`
  - `eval_run_items`
  - `experiences`
- 新增迁移：`cockpit/alembic/versions/0002_create_eval_and_experience.py`
- 新增评测执行器：`cockpit/app/services/eval_runner.py`
- 新增规则评分：`cockpit/app/services/eval_scoring.py`
- 新增 API：
  - `GET/POST/PUT/DELETE /api/v1/eval_cases`
  - `POST /api/v1/eval_runs`
  - `GET /api/v1/eval_runs`
  - `GET /api/v1/eval_runs/{id}`
  - `GET /api/v1/eval_runs/{id}/progress`
  - `GET/POST/PUT/DELETE /api/v1/experiences`
  - `GET /api/v1/assistants`
- 前端新增驾驶舱子页：
  - 评测管理
  - 经验库

## 离线验证

由于当前环境仍无 Docker daemon 权限，尚不能启动 wanwu/cockpit 全链路。已完成源码级实现，待执行以下离线命令补验：

```bash
cd cockpit
pytest -q
```

预期覆盖：

- SSE fixture 增量拼装答案。
- 错误帧提取可读失败原因。
- 关键词评分规则。
- LLM-as-judge 本阶段明确抛出 `NotImplementedError`。

## 待运行验收

以下 5 项需要在具备 Docker 权限、wanwu 可登录、服务账号已注册的环境执行：

1. 探针脚本对真实 assistant 跑通，并把真实样本帧补入 `docs/integration/05-sse-contract.md`。
2. 页面创建 3 个评测用例，发起评测，运行详情能看到每个 case 的答案、首帧延迟、通过状态。
3. 使用不存在的 `assistantId` 发起评测，run 状态为 `failed`，`error_message` 可读。
4. 经验库增删改查和关键词搜索可用。
5. 从阶段 1 数据库直接执行 `alembic upgrade head` 成功，并确认存在 `eval_cases/eval_runs/eval_run_items/experiences`。

## 手动验收命令

组合启动：

```bash
docker compose \
  --env-file wanwu/.env \
  --env-file wanwu/.env.ontology \
  --env-file wanwu/.env.image.arm64 \
  -f wanwu/docker-compose.yaml \
  -f docker-compose.cockpit.yaml \
  up -d
```

数据库迁移检查：

```bash
docker exec cockpit-postgres psql -U cockpit -d cockpit -c '\dt'
```

探针：

```bash
export WANWU_BASE_URL=http://localhost:8081
export WANWU_SVC_USERNAME=<service-account>
export WANWU_SVC_PASSWORD=<service-password>
export WANWU_SVC_CAPTCHA_KEY=<captcha-key>
export WANWU_SVC_CAPTCHA_CODE=<captcha-code>
python cockpit/scripts/probe_assistant_stream.py --assistant-id <assistantId>
```

## 当前限制

- 当前未实测 wanwu assistant SSE 的真实帧，解析规则先由契约文件和 fixture 驱动。
- wanwu 登录接口强依赖验证码；自动化服务账号登录需要验证码环境变量，或使用临时 `WANWU_SVC_TOKEN`。
- 评测执行器目前使用进程内 `asyncio` 任务，服务重启会中断运行中任务；后续若要求生产可靠性，需要接入队列或持久任务调度。
- 未发现 wanwu 侧并发/频率限制的实测结论，需探针补测。
