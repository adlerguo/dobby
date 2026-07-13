# 03 Verify：公共组件 + 模型中心单页试点

本步新增公共组件，并只改造 `ModelHubView.vue` 作为样板页。不改 API 调用、请求字段、路由 path、后端接口和业务数据流。

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

如 backend/maas/postgres 未启动，请按项目常规方式启动完整服务。

## 3. ⚠️ 模型中心视觉验收

打开并强刷：

```text
http://localhost:18080/model-hub
```

检查：

- 顶部为统一 `PageHeader`：
  - 标题“模型中心”
  - 一句话说明
  - 右侧“新建模型”主按钮
- 统计卡片：
  - 4 张卡片等宽排列
  - 12px 圆角、1px 边框、轻阴影
  - 数字约 30px/600
  - 卡片间距 16px
- 模型广场：
  - 卡片信息层级清楚
  - 模型名称 16px/600
  - `provider · model_code` 为等宽字体 13px
  - 能力标签 12px
  - availability 使用 `StatusTag`
  - hover 时边框变色、阴影增强，无位移
- 已接入模型表格：
  - 表头高度约 44px
  - 行高约 52px
  - 状态列为 `StatusTag`
  - 操作列仍为 3 个直接按钮以内
- 接入弹窗：
  - 表单标签在上
  - 必填项有红星
  - API Key 为 password 输入框，带显示/隐藏
  - base_url/API Key 有说明文字
  - 底部按钮主次明确，高度约 36px
- 空状态：
  - 筛选无结果时显示 `EmptyState`
  - 包含标题、说明、下一步按钮

## 4. ⚠️ 模型中心功能回归

逐个验证：

1. 模型广场正常展示。
2. 类型/供应商筛选正常。
3. 点击 `mock-chat` 的“接入使用”，弹窗正常打开。
4. 填写一个新 `runtime_name` 和 `mock-key`，点击“测试并接入”成功。
5. 点击商业模型，填错误 key，弹窗内显示友好错误，弹窗不关闭。
6. 已接入模型列表中，启停模型正常。
7. 点击“渠道”抽屉正常打开。
8. 点击“重新测试”能更新/显示渠道健康状态。
9. 点击“新建模型”弹窗仍可打开，手动新建流程正常。

## 5. ⚠️ 其他页面抽查

确认公共样式没有误伤其他页面，至少抽查：

- `/agents` 智能体工厂
- `/publish` 发布中心
- `/dashboard` 首页工作台

期望：

- 页面能正常打开。
- 表格、按钮、弹窗、标签没有明显异常。
- 控制台无新增报错。

## 6. 本步改动范围

新增：

- `frontend/src/components/common/PageHeader.vue`
- `frontend/src/components/common/StatusTag.vue`
- `frontend/src/components/common/EmptyState.vue`
- `frontend/src/components/common/SectionHeader.vue`

修改：

- `frontend/src/views/ModelHubView.vue`
- `frontend/src/styles/index.css`
- `docs/design/03-verify.md`

本步没有修改：

- API 调用路径
- 请求字段
- 路由 path
- 后端接口
- 其他业务页面结构
