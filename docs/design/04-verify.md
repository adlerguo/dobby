# 04 Verify：核心业务四页 UI 规范铺开

本步将第一批已验收的公共组件铺到四个核心业务页面：

- 智能体工厂 `/agents`
- 知识库实验台 `/kbs`
- 发布中心 `/publish`
- 调试对话 `/chat`

本步不改 API 调用、请求字段、路由 path、后端接口和业务数据流。

## 1. 构建验证

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent/frontend
npm run build
```

期望：构建通过。

## 2. 镜像重建

前端 `dist` 已更新，需要重建 frontend 镜像：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build frontend
```

如依赖服务未启动，请按项目常规方式启动完整服务。

## 3. ⚠️ 智能体工厂 `/agents`

视觉检查：

- 顶部使用 `PageHeader`：标题、说明、右侧“创建智能体”主按钮。
- 智能体列表区使用 `SectionHeader`。
- 状态列使用 `StatusTag`：
  - `draft` 显示草稿灰。
  - `active` 显示可用绿。
- 表格表头约 44px，行高约 52px。
- 空列表时显示 `EmptyState`。
- 创建/编辑表单为 label top，有字段说明。

功能回归：

- 创建智能体。
- 编辑智能体。
- 选择模型。
- 选择知识库。
- 发布草稿智能体。

## 4. ⚠️ 知识库实验台 `/kbs`

视觉检查：

- 顶部使用 `PageHeader`。
- 知识库列表和创建区域使用 `SectionHeader`。
- 知识库状态使用 `StatusTag`。
- 命中测试结果按卡片展示：
  - 文档名/片段序号。
  - 分数标签。
  - 检索模式标签。
  - chunk id 使用等宽字体。
  - 片段正文清晰可读。
- 未测试或无结果时使用 `EmptyState`。

功能回归：

- 创建知识库。
- 选择知识库执行检索。
- 调整 TopK 后再次测试。
- 检查命中片段正文、分数、来源展示正常。

## 5. ⚠️ 发布中心 `/publish`

视觉检查：

- 顶部使用 `PageHeader`。
- 发布应用、已发布应用、API Key 列表使用 `SectionHeader`。
- 发布应用状态使用 `StatusTag`：
  - `published` 绿色。
  - `unpublished` 灰色。
- API Key 前缀使用等宽字体。
- 没有发布应用时使用 `EmptyState`。
- 生成完整 API Key 时，一次性提示醒目，复制按钮可见。

功能回归：

- 选择 active 智能体发布为 API。
- 生成 API Key。
- 复制一次性明文 Key。
- 停用/启用 Key。
- 下线应用。

## 6. ⚠️ 调试对话 `/chat`

视觉检查：

- 顶部使用 `PageHeader`。
- 智能体对话和运行轨迹区使用 `SectionHeader`。
- 用户消息和智能体消息清晰区分。
- 初始空对话使用 `EmptyState`。
- 流式生成中有“生成中...”提示。
- 运行轨迹使用 `StatusTag`。
- 引用 citation 展示为引用卡片：
  - 文档名。
  - 分数。
  - chunk id 等宽字体。
  - 片段内容。

功能回归：

- 选择智能体。
- 发送消息。
- 等待流式回答完成。
- 查看引用卡片。
- 打开引用详情抽屉。
- 复制引用原文。

## 7. ⚠️ 其他页面抽查

确认公共样式没有误伤其他页面，至少抽查：

- `/dashboard`
- `/model-hub`
- `/templates`

期望：

- 页面能正常打开。
- 表格、按钮、卡片、弹窗没有明显异常。
- 控制台无新增报错。

## 8. 本步改动范围

修改：

- `frontend/src/views/AgentListView.vue`
- `frontend/src/views/KnowledgeBaseListView.vue`
- `frontend/src/views/PublishCenterView.vue`
- `frontend/src/views/ChatWorkbenchView.vue`
- `frontend/src/components/common/StatusTag.vue`
- `frontend/src/styles/index.css`
- `docs/design/04-verify.md`

未修改：

- 路由 path
- API 调用路径
- 请求字段
- 后端接口
- 数据流和业务逻辑
