# Step 5c 非流式工具编排缺陷边界确认

执行时间：2026-07-14 Asia/Shanghai

## 结论摘要

Step 5b 发现的 `ContextToolOut.config` 类型错配不只影响流式 `/api/v1/chat`。

实测确认：**非流式 agent 工具编排 `/api/v1/agents/{agent_id}/run` 同样崩溃，返回 HTTP 500**。

对照确认：同一个工具直接调用 `/api/v1/tools/{tool_id}/run` 正常返回 200，说明工具本身可用，缺陷位于 agent 工具编排层 `run_tool_loop()`。

真实边界：

- 受影响：整个 agent 工具编排，包括流式 `stream_agent_events()` 和非流式 `run_agent()`。
- 不受影响：直接工具接口 `/tools/{tool_id}/run`、工具 CRUD、工具权限/隔离类测试。

## 只读代码确认

### 非流式入口

`backend/app/api/v1/agents.py:188-207`

```text
188 @router.post("/agents/{agent_id}/run", response_model=AgentRunOut, summary="Run agent")
195 try:
196     result = await dispatch_single_agent(
...
203 except ValueError as exc:
204     raise agent_error(exc) from exc
```

该接口只捕获 `ValueError`，未捕获 `AttributeError`。

### 非流式 run_agent 同样调用 run_tool_loop

`backend/app/orchestrator/runtime.py:53-65`

```text
53 context = await build_agent_context(...)
```

`build_agent_context()` 返回 `ContextBuildOut`，其 `tools` 字段是 `list[ContextToolOut]`。

`backend/app/orchestrator/runtime.py:111-121`

```text
111 tool_results = await run_tool_loop(
112     db,
...
117     context=context,
118     assistant_text=first_answer,
119     requested_tool_calls=requested_tool_calls,
120     max_tool_rounds=payload.max_tool_rounds,
121 )
```

### ContextToolOut 来源

`backend/app/orchestrator/context.py:358-359`

```text
358 def tool_out(tool: Tool) -> ContextToolOut:
359     return ContextToolOut(id=tool.id, name=tool.name, type=tool.type, tool_schema=tool.schema or {})
```

`backend/app/schemas/context.py:28-37`

```text
28 class ContextToolOut(BaseModel):
31     id: UUID
32     name: str
33     type: str
34     tool_schema: dict[str, Any]
```

没有 `config` 字段。

### 崩溃点

`backend/app/orchestrator/runtime.py:637`

```text
if is_code_tool(tool) and not is_code_tool_allowed(tool):
```

`backend/app/orchestrator/runtime.py:698-700`

```text
698 def is_code_tool(tool: Tool) -> bool:
699     config = tool.config or {}
700     builtin = str(config.get("builtin") or "").lower()
```

这里把 `ContextToolOut` 当 ORM `Tool` 使用，导致 `AttributeError`。

## 实测结果

复现脚本：

- `qa/scripts/step5c_nonstream_toolcheck.py`

证据文件：

- `qa/env/step5c-nonstream-results.json`
- `qa/env/step5c-nonstream-output.json`
- `qa/env/step5c-backend.log`
- `qa/env/step5c-db-state.json`

### 1. 非流式 agent 工具编排

请求：

```text
POST /api/v1/agents/d1bc369d-de64-4f43-8aec-fdc89e2ca27e/run
```

body 摘要：

```json
{
  "query": "calculate 2+3 using calculator",
  "tool_calls": [
    {
      "tool_id": "0fe54bec-049a-405b-a670-8df101a7d11f",
      "input": {"expression": "2+3"}
    }
  ],
  "max_tool_rounds": 1
}
```

实际响应：

```json
{
  "status": 500,
  "body": "Internal Server Error"
}
```

### 2. 直接工具接口对照

请求：

```text
POST /api/v1/tools/0fe54bec-049a-405b-a670-8df101a7d11f/run
body: {"input":{"expression":"2+3"}}
```

实际响应：

```json
{
  "status": 200,
  "body": {
    "tool_id": "0fe54bec-049a-405b-a670-8df101a7d11f",
    "type": "builtin",
    "status": "ok",
    "output": {
      "value": 5.0
    }
  }
}
```

结论：calculator 工具本身正常，agent 编排层崩溃。

### 3. nl2data 示例 agent

alice 所属 QA 租户没有 `nl2data` agent：

```json
"alice_nl2data_agents": []
```

全库存在 default 租户示例：

```json
{
  "name": "示例智能问数 Agent",
  "status": "active",
  "tenant_code": "default"
}
```

本轮没有用 alice token 跨租户调用 default 示例 agent。基于代码路径判断：`nl2data` 的 `auto_tool_calls()` 同样会进入 `run_tool_loop()`，且只要工具能绑定成功，也会触发同一 `ContextToolOut.config` 问题。

## 日志堆栈

`qa/env/step5c-backend.log` 摘要：

```text
backend-1  | INFO:     192.168.65.1:55534 - "POST /api/v1/agents/d1bc369d-de64-4f43-8aec-fdc89e2ca27e/run HTTP/1.1" 500 Internal Server Error
backend-1  | ERROR:    Exception in ASGI application
...
backend-1  |   File "/app/app/api/v1/agents.py", line 196, in run_agent_api
backend-1  |     result = await dispatch_single_agent(
backend-1  |   File "/app/app/orchestrator/runtime.py", line 27, in dispatch_single_agent
backend-1  |     return await run_agent(db, tenant_id=tenant_id, user_id=user_id, agent_id=agent_id, payload=payload)
backend-1  |   File "/app/app/orchestrator/runtime.py", line 111, in run_agent
backend-1  |     tool_results = await run_tool_loop(
backend-1  |   File "/app/app/orchestrator/runtime.py", line 637, in run_tool_loop
backend-1  |     if is_code_tool(tool) and not is_code_tool_allowed(tool):
backend-1  |   File "/app/app/orchestrator/runtime.py", line 699, in is_code_tool
backend-1  |     config = tool.config or {}
backend-1  |   File "/usr/local/lib/python3.11/site-packages/pydantic/main.py", line 1042, in __getattr__
backend-1  |     raise AttributeError(f'{type(self).__name__!r} object has no attribute {item!r}')
backend-1  | AttributeError: 'ContextToolOut' object has no attribute 'config'
```

## DB 状态

非流式 500 后，该 tool agent 没有新 conversation 持久化：

```json
{
  "tool_agent_id": "d1bc369d-de64-4f43-8aec-fdc89e2ca27e",
  "latest_tool_agent_conversations": []
}
```

说明异常导致请求事务回滚；与流式路径类似，agent 编排没有形成完整可审计记录。

## 缺陷定级建议

建议定级：**P0 或最高优先 P1**。

数据支撑：

- 不是单一流式 UI 问题，非流式 agent run 也 500。
- 不是工具实现问题，直接 `/tools/{id}/run` 正常。
- 影响所有 agent 工具编排成功路径：
  - 显式 `tool_calls`
  - 模型输出可解析 tool calls
  - `nl2data` 自动工具调用路径
- 流式表现为 HTTP 200 后半截断流；非流式表现为 HTTP 500。
- 成功绑定工具时必然走 `is_code_tool(tool)`，而 `context.tools` 必然是 `ContextToolOut`。

若产品把“Agent 调工具”作为核心能力，建议按 P0 处理；若当前版本工具编排尚未进入上线承诺，可按 P1-blocker 处理。

## Step 6 可执行性

可继续执行、不受此缺陷影响：

- `/api/v1/tools` CRUD
- `/api/v1/tools/{tool_id}/run` 直接执行
- 工具权限、租户隔离、安全边界
- R1/R2/R7 这类直接工具安全用例

受阻或需标记已知阻断：

- `/api/v1/agents/{agent_id}/run` 的工具编排成功路径
- `/api/v1/chat` 的工具流式编排成功路径
- nl2data agent 通过 agent 编排自动调用工具的成功路径

最终边界结论：

```text
缺陷影响：流式 + 非流式 agent 工具编排
不影响：直接工具接口本身
```
