# OpenAI 兼容 API 接入说明

面向企业集成方，用标准 OpenAI 客户端直接调用已发布的智能体，零改造接入。底层复用同一套 API Key 鉴权、限流、配额与计费，仅把请求/响应换成 OpenAI Chat Completions 形状。已有的 `/public/apps/{app_id}/chat` 自定义端点继续保留，两者互不影响。

## 1. 前置条件
1. 目标智能体已在发布中心发布为应用（状态 published）。
2. 已为该应用创建 active、未过期的 API Key。
3. 已拿到应用 ID `app_id` 与 API Key 明文（仅创建时展示一次）。

## 2. Base URL 与鉴权
```text
Base URL：  https://<host>/api/v1/public/apps/<app_id>/openai/v1
鉴权：      Authorization: Bearer <API Key>
```
- Base URL 带 `app_id` 是刻意设计，鉴权会校验 Key 属于该 app_id，不匹配返回 403。
- OpenAI 官方 SDK 支持自定义 base_url，填入即可，客户端代码无需改动。
- `model` 参数仅用于响应回显，不参与模型路由；实际模型由该应用绑定的智能体配置决定，可填任意占位字符串。

## 3. 接口：POST /chat/completions
完整路径：`https://<host>/api/v1/public/apps/<app_id>/openai/v1/chat/completions`

请求字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| model | string | 是 | 占位符，仅回显 |
| messages | array | 是 | `{role, content}` 列表，至少一条 role=user |
| stream | boolean | 否 | 默认 false；true 为 SSE 流式 |
| max_tokens | integer | 否 | 会被限制到 [256, 32000] |
| temperature/top_p | number | 否 | 当前接收但不生效 |
| stream_options | object | 否 | `{include_usage:true}` 时流式结尾追加 usage |

多轮为无状态：每次由客户端在 messages 携带完整上下文，服务端取最后一条 user 消息为本轮提问，更早轮次会拼为上下文前言并入提问。

## 4. 非流式示例
```bash
curl https://<host>/api/v1/public/apps/<app_id>/openai/v1/chat/completions \
  -H "Authorization: Bearer <API Key>" \
  -H "Content-Type: application/json" \
  -d '{"model":"agent","messages":[{"role":"user","content":"总结产品的三个核心能力"}]}'
```
```python
from openai import OpenAI
client = OpenAI(base_url="https://<host>/api/v1/public/apps/<app_id>/openai/v1", api_key="<API Key>")
resp = client.chat.completions.create(model="agent", messages=[{"role":"user","content":"..."}])
print(resp.choices[0].message.content)
```
响应为标准 `chat.completion` 对象（id/object/created/model/choices/usage）；若回答有引用，放在扩展字段 `x_citations`，标准客户端会忽略。

## 5. 流式
`stream=true` 返回 `text/event-stream`，帧以 `data:` 开头，末尾 `data: [DONE]`。首帧 role、多帧 content 增量、末帧 finish_reason=stop。
```python
stream = client.chat.completions.create(model="agent", messages=[...], stream=True)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

## 6. 限流与配额
按 API Key 维度，流式与非流式共用额度，超限返回 429 并带 Retry-After。可配维度：每分钟速率、每日请求数、每日 Token、每日成本。0 表示不限。

## 7. 错误格式
```json
{"error":{"message":"...","type":"invalid_request_error","code":"..."}}
```
| HTTP | 场景 |
|---|---|
| 400 | 缺 user 消息、请求体不合法 |
| 401 | 缺失/无效 API Key |
| 403 | Key 与 app_id 不匹配，或应用/智能体不可用 |
| 409 | 该智能体无可用模型渠道 |
| 429 | 触发速率或配额，见 Retry-After |

## 8. 能力边界（当前版本）
- 工具调用未从该接口暴露（智能体内部配置的工具照常在编排中生效）。
- temperature/top_p 接收但不生效。
- model 仅回显、不路由。
- 无状态：不接受/返回 conversation_id。
