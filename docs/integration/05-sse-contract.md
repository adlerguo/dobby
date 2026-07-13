# Assistant SSE 契约记录

## 当前状态

当前环境仍不能访问 Docker daemon socket，阶段 1 的 5 项运行验收尚未补验通过。因此本阶段尚未取得真实运行帧。

本文件先登记源码证据、探针脚本和离线 fixture。后续在具备 Docker 权限并注册评测服务账号后，必须用探针脚本补写“实测样本帧”和异常场景。

## 源码证据

- 登录路由：`wanwu/internal/bff-service/server/http/handler/router/v1/guest.go`
  - `POST /v1/base/login`
  - `GET /v1/base/captcha`
  - `GET /v1/base/rsa/public-key`
- 登录请求结构：`wanwu/internal/bff-service/model/request/guest.go`
  - `username`
  - `cipher`
  - `keyId`
  - `key`
  - `code`
- RSA 加密前端实现：`wanwu/web/src/utils/crypto.js`
  - 明文为 `{"password": "...", "challenge": "..."}`
  - 加密算法为 RSA-OAEP + SHA256
- assistant 流式路由：`wanwu/internal/bff-service/server/http/handler/router/v1/assistant.go`
  - `POST /v1/assistant/stream/draft`
- assistant 流式请求结构：`wanwu/internal/bff-service/model/request/assistant.go`
  - `assistantId`
  - `conversationId`
  - `fileInfo`
  - `prompt`
  - `systemPrompt`
  - `isCompare`
  - `sseHold`
- assistant SSE 响应结构：`wanwu/internal/bff-service/model/response/assistant.go`
  - `code`
  - `message`
  - `response`
  - `order`
  - `eventType`
  - `eventData`
  - `finish`
  - `usage`
  - `search_list`
  - `responseFiles`
- 前端消费逻辑：`wanwu/web/src/mixins/sseMethod.js`
  - draft 入口为 `/assistant/stream/draft`
  - 成功帧判断 `data.code === 0`
  - 主回复字段为 `data.response`
  - 会话字段为 `data.conversationId`
  - 结束判断依赖 `data.finish`

## 探针脚本

脚本位置：`cockpit/scripts/probe_assistant_stream.py`

运行前需要在 wanwu 界面注册专用评测服务账号，并准备以下环境变量：

```bash
export WANWU_BASE_URL=http://localhost:8081
export WANWU_SVC_USERNAME=<service-account>
export WANWU_SVC_PASSWORD=<service-password>
export WANWU_SVC_CAPTCHA_KEY=<captcha-key>
export WANWU_SVC_CAPTCHA_CODE=<captcha-code>
```

如果验证码无法自动化，可先从浏览器登录或调试工具中取得服务账号 token，临时使用：

```bash
export WANWU_SVC_TOKEN=<service-account-jwt>
```

执行：

```bash
python cockpit/scripts/probe_assistant_stream.py \
  --assistant-id <assistantId> \
  --prompt "请用一句话回答：这是一次评测探针吗？"
```

脚本会：

- 调用 `/service/api/v1/base/rsa/public-key` 获取 `keyId/publicKey/challenge`；
- 按前端源码一致的 RSA-OAEP-SHA256 生成 `cipher`；
- 调用 `/service/api/v1/base/login` 获取 JWT；
- 调用 `/service/api/v1/assistant/stream/draft`；
- 原样打印每个 SSE `data:` 帧；
- 统计首帧延迟、总耗时、帧数、拼装答案、结束帧、错误帧和 usage。

## 待实测样本帧

尚未实测。以下仅为离线测试 fixture，来源于 BFF 响应结构与前端消费逻辑，用于保证 cockpit 解析器不把帧结构写死在代码中。

```json
{"code":0,"message":"","response":"你好，","order":1,"eventType":0,"finish":0,"conversationId":"conv-fixture-001","usage":{"prompt_tokens":3,"completion_tokens":0,"total_tokens":3}}
{"code":0,"message":"","response":"我是测试回答。","order":2,"eventType":0,"finish":1,"conversationId":"conv-fixture-001","usage":{"prompt_tokens":3,"completion_tokens":7,"total_tokens":10}}
```

错误 fixture：

```json
{"code":1001,"message":"assistant not found","response":"","finish":1}
```

## 解析规则

契约文件：`cockpit/app/contracts/assistant_stream_contract.json`

- 成功帧：`code == 0`
- 文本字段：`response`
- 拼装方式：当前 fixture 采用增量拼接；实测后如发现为全量覆盖，需要把契约文件 `content_mode` 改为 `full`
- 会话字段：`conversationId`
- 结束字段：`finish`
- 终止值：当前按前端逻辑登记为 `1/2/4`，实测后确认
- usage：`usage.prompt_tokens / usage.completion_tokens / usage.total_tokens`
- 错误帧：`code != 0` 时从 `response` 或 `message` 取可读错误

## 异常场景

待用探针补测：

1. `assistantId` 不存在。
2. token 过期。
3. 服务账号无组织或无 assistant 权限。
4. 并发流式调用时的限流/排队行为。
