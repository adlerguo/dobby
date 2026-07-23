# API 错误码说明

本文区分平台三类 API 的错误响应格式。调用方应先按接口族判断格式，再读取 `error.code` 或旧版兼容字段。

## 管理后台 API

适用范围：`/api/v1/agents`、`/api/v1/kbs`、`/api/v1/model-center` 等后台管理接口。

统一错误格式：

```json
{
  "error": {
    "code": "not_found",
    "message": "agent_not_found",
    "detail": null
  }
}
```

| code | HTTP | 含义 | 处理 |
|---|---:|---|---|
| not_found | 404 | 资源不存在或已归档 | 刷新列表后重试 |
| agent_name_exists | 409 | 智能体名称已存在 | 更换名称 |
| kb_name_exists | 409 | 知识库名称已存在 | 更换名称 |
| document_name_exists | 409 | 同一知识库存在同名文档 | 更名或删除旧文档 |
| model_name_exists | 409 | 模型名称已存在 | 更换运行时名称 |
| no_active_model_channel | 409 | 没有可用模型渠道 | 到模型中心接入并启用渠道 |
| kb_embedding_model_locked_has_documents | 409 | 知识库已有文档，向量模型已锁定 | 新建知识库并重新上传 |
| agent_template_not_found | 404 | 智能体模板不存在 | 重新选择模板 |
| model_not_found | 404 | 模型不存在 | 重新选择模型 |
| model_catalog_not_found | 404 | 模型目录项不存在 | 刷新模型目录 |
| channel_not_found | 404 | 模型渠道不存在 | 刷新渠道列表 |
| agent_template_type_mismatch | 422 | 模板类型与智能体类型不一致 | 重新选择模板 |
| protocol_not_supported | 422 | 模型协议暂不支持一键接入 | 手动创建模型渠道 |
| model_type_not_supported | 422 | 模型类型暂不支持一键接入 | 选择 LLM 或 embedding 模型 |
| connection_test_failed | 422 | 连接测试失败 | 检查访问密钥、服务地址和供应商状态 |
| maas_probe_failed | 502 | MaaS 探活失败 | 检查 MaaS 服务和上游网络 |
| model_channel_create_failed | 502 | 模型渠道创建失败 | 检查 MaaS 服务和请求参数 |

## 公开应用 API

适用范围：发布后的应用调用接口，例如公开聊天、应用密钥访问等。

错误格式保持 OpenAI 风格：

```json
{
  "error": {
    "message": "app_unavailable",
    "type": "invalid_request_error",
    "code": "app_unavailable"
  }
}
```

| code / 提示 | HTTP | 含义 | 处理 |
|---|---:|---|---|
| 缺失/无效 API Key | 401 | 未带或错误的 Bearer Key | 检查 Authorization 头与 Key |
| app_forbidden | 403 | Key 与 app_id 不匹配 | 使用该应用自己的 Key |
| app_unavailable | 403 | 应用或绑定智能体不可用 | 确认发布状态、智能体已启用 |
| quota_exceeded | 429 | 触发密钥速率或每日配额 | 稍后重试或调整密钥限额 |

## OpenAI 兼容 API

适用范围：`/api/v1/openai/*` 或其他声明兼容 OpenAI 的端点。

错误格式遵循 OpenAI 兼容形状：

```json
{
  "error": {
    "message": "invalid_request",
    "type": "invalid_request_error",
    "code": "invalid_request"
  }
}
```

| code | HTTP | 含义 | 处理 |
|---|---:|---|---|
| invalid_request | 400 | 请求体不合法或缺少 user 消息 | 按接口文档修正请求 |
| stream_not_supported | 400 | 当前端点不支持流式 | 使用支持流式的端点或去掉 stream |
| no_active_model_channel | 409 | 无可用真实模型渠道 | 模型中心接入 Key 并测试连通 |
| provider_http_401 | 4xx | 供应商拒绝访问 | 到供应商后台核对 Key、余额和权限 |
| rate_limited | 429 | 上游或渠道限流 | 稍后重试 |
| channel_failed | 502 | 渠道连续失败或被熔断 | 检查该渠道配置，等待探活恢复 |

## 知识库与工具补充

| code | 含义 | 处理 |
|---|---|---|
| dimension_mismatch | 知识库向量维度与模型不一致 | 使用创建时选定的向量模型；换模型需新建库或重建索引 |
| document_parse_failed | 文档解析失败 | 检查文档格式，重传或拆分 |
| code_tool_disabled | 代码类工具默认禁用 | 管理员开启 `enable_auto_code_tools` 并配置允许清单 |
| http_host_not_allowed | 目标主机不在 HTTP 白名单 | 管理员将主机加入 HTTP 工具白名单 |
| mcp_execution_unavailable | 外部 MCP 执行暂不可用 | 当前仅可保存配置，暂不执行 |

> 说明：具体 code 命名以当前版本接口实现为准；本表用于排查方向，交付时可对照实际返回补全。
