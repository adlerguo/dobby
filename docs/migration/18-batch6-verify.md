# 批次6验证：一键部署 + 教程 + 示例数据 + 沙箱最小加固

## 1. 一键启动

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
./deploy/quickstart.sh
```

期望：

- backend / maas / sandbox / frontend 全部启动。
- backend 自动执行 `alembic upgrade head`。
- 首启密钥由批次1逻辑生成并保存在 Docker volume `app_secrets`。
- 浏览器访问 `http://localhost:18080/quickstart` 能看到四步向导。

显式演示模式：

```bash
SEED_DEMO_MODE=true ./deploy/quickstart.sh
```

期望：mock 目录项和示例 Agent 只在该模式下注入，UI 标注“演示模型（非真实）”。

## 2. Quickstart 主链路

1. 登录 `http://localhost:18080`：`default / admin / Admin123!`。
2. 进入“快速开始”，点击“去模型中心”。
3. 接入真实 LLM 和 embedding 模型，并测试连通。
4. 进入“知识库实验台”，创建知识库，上传：
   - `examples/docs/enterprise-ai-platform.txt`
   - `examples/docs/contract-approval-guidelines.md`
5. 等文档状态到“完成”。
6. 创建智能体，绑定该知识库。
7. 进入“调试对话”，提问：

```text
企业智能体中台的上线流程是什么？
合同审批需要重点检查哪些内容？
```

期望：返回真实模型答案，右侧引用卡片可点击定位来源文档/切片。

## 3. 沙箱最小加固

启动沙箱后检查非 root：

```bash
docker compose exec sandbox id
```

期望：用户为 `sandbox`，不是 root。

超时验证：

```bash
curl -s -X POST http://localhost:8200/exec \
  -H 'Content-Type: application/json' \
  -d '{"type":"python","code":"while True: pass","timeout_seconds":1}'
```

期望：返回 `timed_out: true` 或进程被资源限制终止，不拖垮宿主。

内存限制验证：

```bash
curl -s -X POST http://localhost:8200/exec \
  -H 'Content-Type: application/json' \
  -d '{"type":"python","code":"x=[]\nwhile True:\n    x.append(\"x\"*1024*1024)","timeout_seconds":5}'
```

期望：进程被杀掉或返回 MemoryError，服务本身仍可继续响应 `/healthz`。

## 4. 自动代码工具保护

默认环境下，后端配置：

```text
ENABLE_AUTO_CODE_TOOLS=false
CODE_TOOL_ALLOWLIST=
```

期望：智能体自动触发 code/python/shell/sandbox 类工具时返回 `auto_code_tool_disabled`，不会调用沙箱执行代码。

需要显式允许时，只允许可信部署配置白名单：

```text
CODE_TOOL_ALLOWLIST=可信工具名或工具ID
```

## 5. 回归清单

- 模型中心真实渠道接入和连通性测试正常。
- 未配置真实渠道时不返回 `mock response:`。
- 知识库上传、切片查看、命中测试正常。
- 调试对话流式输出和引用卡片正常。
- 发布 API Key 和外部调用正常。
- 观测中心、审计记录、工作空间页面可正常打开。
