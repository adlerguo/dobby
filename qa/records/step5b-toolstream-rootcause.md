# Step 5b 工具循环流式断流根因定位

执行时间：2026-07-14 Asia/Shanghai

## 复现结论

Step 5 第 4 组的工具循环流式断流是 **(b) 工具执行阶段抛出未捕获异常**，不是工具执行成功后的最终答案拼接问题。

直接根因：

- `stream_agent_events()` 把 `context.tools` 传给 `run_tool_loop()`。
- `context.tools` 的元素类型是 `ContextToolOut`，只包含 `id/name/type/tool_schema`。
- `run_tool_loop()` 中解析到工具后，把 `ContextToolOut` 当作 ORM `Tool` 使用，调用 `is_code_tool(tool)`。
- `is_code_tool()` 读取 `tool.config`。
- `ContextToolOut` 没有 `config` 字段，因此抛出 `AttributeError: 'ContextToolOut' object has no attribute 'config'`。
- 该异常不是 `ValueError`，没有被 `chat.py` 的 `except ValueError` 捕获，导致 Starlette StreamingResponse 生成器崩溃，客户端收到 delta 后 IncompleteRead，没有 `done`。

## 代码路径

只读代码定位：

- `backend/app/api/v1/chat.py:93-117`
  - `stream_chat_events()` 包住 `run_stream_agent_events(...)` 的外层循环。
  - 只捕获 `ValueError`：

```text
93  async def stream_chat_events(...)
95      try:
96          async for event in run_stream_agent_events(...):
114             yield sse_event(event["event"], event["data"])
115     except ValueError as exc:
116         yield sse_event("error", {"detail": str(exc)})
```

- `backend/app/orchestrator/runtime.py:265-289`
  - 只把首段 MaaS 流式调用 `call_maas_chat_stream(...)` 放进局部 `try/except ValueError`。
  - 这解释了为什么模型失败能转为 `error` 事件。

```text
265 try:
266     async for event in call_maas_chat_stream(...):
...
282 except ValueError as exc:
283     root_trace.status = "failed"
...
288     yield {"event": "error", "data": {"detail": str(exc)}}
289     return
```

- `backend/app/orchestrator/runtime.py:291-318`
  - `run_tool_loop(...)` 和后续非流式最终答案 `call_maas_chat(...)` 在上述局部 `try` 之外。
  - 理论上若它们抛 `ValueError`，可被 `chat.py:115` 外层捕获；但非 `ValueError` 会直接崩溃。

```text
291 answer = "".join(answer_parts)
292 tool_results = await run_tool_loop(...)
303 if tool_results:
304     final_messages = [...]
305     final_response = await call_maas_chat(...)
318     yield {"event": "delta", "data": {"text": "\n\n" + answer}}
```

- `backend/app/orchestrator/runtime.py:611-621`
  - `run_tool_loop()` 从 `context.tools` 中按 id/name 找工具。
  - 找不到会抛 `ValueError("tool_not_bound")`，这个可被外层转为 SSE error。

```text
611 available_by_id = {tool.id: tool for tool in context.tools}
...
620 if tool is None:
621     raise ValueError("tool_not_bound")
```

- `backend/app/orchestrator/runtime.py:637-652`
  - 找到工具后立刻检查是否是 code tool。
  - 这里调用 `is_code_tool(tool)`。

```text
637 if is_code_tool(tool) and not is_code_tool_allowed(tool):
...
652 output = await run_tool(db, tenant_id=tenant_id, tool_id=tool.id, input=call.input)
```

- `backend/app/orchestrator/runtime.py:698-703`
  - `is_code_tool()` 需要 `tool.config`。

```text
698 def is_code_tool(tool: Tool) -> bool:
699     config = tool.config or {}
700     builtin = str(config.get("builtin") or "").lower()
701     return tool.type == "code" or builtin in {"code", "python", "shell", "sandbox"}
```

- `backend/app/schemas/context.py:28-37`
  - `ContextToolOut` 没有 `config`。

```text
28 class ContextToolOut(BaseModel):
31     id: UUID
32     name: str
33     type: str
34     tool_schema: dict[str, Any]
```

## 复现证据

复现脚本：

- `qa/scripts/step5b_repro_toolstream.py`

请求使用 Step 5 已创建的 tool agent，并显式传入绑定工具：

```json
{
  "agent_id": "d1bc369d-de64-4f43-8aec-fdc89e2ca27e",
  "query": "calculate 2+3 using the calculator tool",
  "tool_calls": [
    {
      "tool_id": "0fe54bec-049a-405b-a670-8df101a7d11f",
      "input": {"expression": "2+3"}
    }
  ],
  "max_tool_rounds": 1
}
```

客户端结果：

```text
HTTP 200
read_error=IncompleteRead
events=delta x 8
done 缺失
error 事件缺失
```

响应片段见：

- `qa/env/step5b-repro-response.json`
- `qa/env/step5b-repro-output.json`

## 服务端日志堆栈

日志文件：

- `qa/env/step5b-backend.log`

关键堆栈：

```text
backend-1  | INFO:     192.168.65.1:40093 - "POST /api/v1/chat HTTP/1.1" 200 OK
backend-1  | ERROR:    Exception in ASGI application
backend-1  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
...
backend-1  |   File "/app/app/api/v1/chat.py", line 96, in stream_chat_events
backend-1  |     async for event in run_stream_agent_events(
backend-1  |   File "/app/app/orchestrator/runtime.py", line 292, in stream_agent_events
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

复现后查该 tool agent 最新 conversation：

```json
{
  "agent_id": "d1bc369d-de64-4f43-8aec-fdc89e2ca27e",
  "latest_conversation": []
}
```

证据文件：

- `qa/env/step5b-db-state.json`

说明：

- 前面的 delta 已经发给客户端。
- 但异常发生后 StreamingResponse 崩溃，`async with SessionLocal()` 退出，未提交事务。
- 因此 conversation/user message/root trace 都没有持久化。
- 这比 Step 5 的模型失败路径更差：模型失败路径至少有 failed trace 和 user message；工具路径本次是半截响应 + 回滚。

## 与模型失败路径的差异

模型失败路径：

- 失败发生在 `call_maas_chat_stream(...)` 内。
- 该调用被 `runtime.py:265-289` 的局部 `try/except ValueError` 覆盖。
- 代码会设置：
  - `root_trace.status = "failed"`
  - `root_trace.output = {"error": ...}`
  - `db.commit()`
  - `yield {"event": "error", ...}`

工具路径：

- 首段模型流已成功，并已向客户端发送多个 `delta`。
- 随后执行 `runtime.py:292` 的 `run_tool_loop(...)`。
- 该阶段不在局部 `try` 内。
- 实际抛出的是 `AttributeError`，不是 `ValueError`。
- `chat.py:115` 也只捕获 `ValueError`，因此异常穿透到 Starlette StreamingResponse，造成连接断流。

## 影响面

影响所有“实际进入工具执行”的流式对话：

- 绑定任意工具的 agent，只要显式 `tool_calls` 或模型输出可解析的 `tool_calls`，并且工具能在 `context.tools` 中按 id/name 找到，就会走到 `is_code_tool(tool)`。
- 因为 `context.tools` 的元素都是 `ContextToolOut`，不是 ORM `Tool`，所以 builtin/http/code 工具都会在 `tool.config` 处失败。
- `tool_not_bound` 这种找不到工具的情况会抛 `ValueError`，反而能被转成 SSE error；真正绑定成功的工具更容易触发本 P1。
- `nl2data` 示例 agent 若走 `auto_tool_calls()` 并找到绑定工具，也会进入同一路径，预期同样受影响。

补充影响：

- 非流式 `run_agent()` 也调用同一个 `run_tool_loop()`，同样存在类型错配风险；本次未扩展执行非流式接口，只记录代码风险。
- 普通无工具 agent 不受影响。

## 修复建议方向（未实施）

只提方向，不修改代码：

1. `run_tool_loop()` 不应把 `ContextToolOut` 当 ORM `Tool` 使用。
   - 方案 A：`ContextToolOut` 增加必要的 `config/status` 字段，但需注意不要把敏感配置泄露给上下文。
   - 方案 B：`run_tool_loop()` 根据 `tool_id` 从 DB 重新加载 ORM `Tool`，再执行 `is_code_tool()` 与 `run_tool()`。
   - 方案 C：`ContextBuildOut.tools` 保留给模型上下文，工具执行阶段使用单独的内部 Tool 对象列表。

2. 扩大流式工具阶段异常边界。
   - 将 `run_tool_loop()` 和 `call_maas_chat(... name="maas_final")` 纳入可控 `try`。
   - 对所有异常至少转为 SSE `error` 事件，并把 root trace 标记 failed 后 commit。
   - 不建议只捕获 `ValueError`；至少应捕获预期业务异常和兜底 `Exception`，避免已发 delta 后断流。

3. 工具阶段应有显式事件契约。
   - 例如 `tool_start` / `tool_result` / `delta` / `done` / `error`。
   - 避免用户只看到首段模型回答，工具阶段发生异常时无法感知。

## Step 6 影响

该 P1 会影响 Step 6 工具测试的可执行性：

- 若 Step 6 通过 `/api/v1/chat` 流式方式验证工具调用，当前无法可靠完成成功路径。
- 可以继续测试直接工具接口 `/api/v1/tools/{tool_id}/run`、工具 CRUD、权限和隔离。
- 但“agent 工具编排/工具循环/工具结果二次回答”的流式成功路径会被该缺陷阻断，建议 Step 6 将其标为已知阻断或先只测非流式/直接工具接口。

## 最终结论

断流类型：**(b) 工具执行阶段异常未捕获**。

精确根因：`run_tool_loop()` 使用 `ContextToolOut` 调 `is_code_tool()`，而 `ContextToolOut` 没有 `config`，触发 `AttributeError`。该异常不在流式错误处理边界内，导致 StreamingResponse 断流、无 `done`、无 `error`、无落库提交。
