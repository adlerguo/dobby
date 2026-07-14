# 6qiyeagent 快速开始

本教程按真实交付路径走完“配模型 → 建知识库 → 上传文档 → 问答验证”。默认路径要求配置真实模型 API；mock 只作为显式演示分支，不会在生产模式下静默返回假答案。

## 1. 一条命令启动

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
./deploy/quickstart.sh
```

打开 `http://localhost:18080`，默认登录：

```text
租户：default
用户：admin
密码：Admin123!
```

首次启动会自动生成并持久化运行密钥。再次启动会复用同一份密钥，避免已加密模型渠道失效。

## 2. 配置真实模型 API

进入“模型中心”，从模型广场选择真实模型并点击“接入使用”。

推荐最小组合：

- 对话模型：DeepSeek Chat、GPT-4o mini 或通义千问 Plus。
- 向量模型：BGE-large-zh、通义 text-embedding-v4 或 text-embedding-3-small。

填写 API Key 后先点“测试并接入”。测试失败时不会写入可用渠道，请检查 Key、Base URL 和服务商余额。

## 3. 创建知识库并上传示例文档

进入“知识库实验台”，创建知识库。embedding 模型请选择刚接入并测试通过的向量模型。

上传示例资料：

- `examples/docs/enterprise-ai-platform.txt`
- `examples/docs/contract-approval-guidelines.md`

等待文档状态变为“完成”后，再进行命中测试。

## 4. 创建智能体并体验问答

进入“智能体工厂”，创建一个 QA 智能体：

- 模型：选择刚接入的真实对话模型。
- 知识库：选择刚建好的知识库。
- 召回参数：默认 `top_k=3`、`match_type=hybrid` 即可。

进入“调试对话”，选择该智能体并提问：

```text
企业智能体中台的上线流程是什么？
合同审批需要重点检查哪些内容？
```

预期结果：回答来自真实模型，右侧能看到引用证据，点击引用可定位来源文档和切片。

## 显式演示数据

如果只是离线演示，可以显式开启：

```bash
SEED_DEMO_MODE=true ./deploy/quickstart.sh
```

演示模型会在 UI 中标注“演示模型（非真实）”。生产模式下 mock 渠道不会参与真实路由。

## 常见问题

### 提示 no_active_model_channel

说明还没有可用的真实模型渠道，或渠道被停用。请到模型中心配置 API Key 并测试连通。

### provider_http_401

服务商拒绝了请求，通常是 API Key 错误、权限不足或账号欠费。

### 3072 维 embedding 检索慢

当前 3072 维向量没有 HNSW 索引，适合小库验证。大库建议使用 1024/1536 维模型，或在 v2 使用 halfvec HNSW/降维方案。

### 已有文档的知识库不能切换 embedding 模型

这是为了避免旧向量被孤立导致“文档还在但搜不到”。需要换模型时，请新建知识库或执行重建索引流程。

### 沙箱能否直接用于 SaaS 多租户？

不能。当前沙箱是本地可信环境的最小加固版本；SaaS/多租户需要替换为 gVisor、nsjail 或独立容器池强隔离方案。
