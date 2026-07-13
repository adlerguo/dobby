# 02 Verify：主布局与深色侧边导航

本步改造主布局、左侧导航、顶部栏和账户区。不改 API、路由 path、请求字段和业务逻辑。

## 1. 构建验证

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent/frontend
npm run build
```

期望：构建通过。

## 2. 镜像重建

本步改了前端依赖和 `dist`，需要重建 frontend 镜像：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build frontend
```

如果服务没有运行，可按项目常规方式启动依赖和 backend。

## 3. 浏览器视觉检查

打开：

```text
http://localhost:18080
```

如页面已打开，请按 `Cmd+Shift+R` 强制刷新。

⚠️ 检查项：

- 左侧侧边栏为深色背景 `#111827`。
- 侧边栏宽度约 232px。
- 顶部产品标识在深色背景下可读。
- 导航按五组显示：
  - 工作台
  - 构建
  - AI资源
  - 运营
  - 管理
- 图标为统一线性风格。
- 导航项高度约 40px。
- Hover 有深灰背景。
- Active 为蓝紫半透明背景，文字和图标提亮。
- 顶部栏只保留当前页面上下文和搜索框，不再有独立“退出”按钮。
- 底部账户区显示用户名和租户简写。

## 4. 菜单逐项验证

⚠️ 逐个点击全部 11 个菜单项，确认页面正常打开、无空白页、无控制台报错：

| 分组 | 菜单 | path |
| --- | --- | --- |
| 工作台 | 首页工作台 | `/dashboard` |
| 构建 | 智能体工厂 | `/agents` |
| 构建 | 模板广场 | `/templates` |
| 构建 | 调试对话 | `/chat` |
| AI资源 | 模型中心 | `/model-hub` |
| AI资源 | 知识库实验台 | `/kbs` |
| AI资源 | 工具中心 | `/tools` |
| 运营 | 发布中心 | `/publish` |
| 运营 | 观测中心 | `/observability` |
| 管理 | 工作空间 | `/workspaces` |
| 管理 | 审计记录 | `/audit` |

期望：

- Active 态跟随当前页面正确变化。
- `/model-hub` 菜单显示为“模型中心”。
- 模型中心页面内主标题也显示“模型中心”。

## 5. 账户菜单验证

⚠️ 操作：

1. 点击侧边栏底部账户区。
2. 菜单向上弹出。
3. 点击“退出登录”。
4. 应跳转到登录页。
5. 重新登录后可正常回到系统。

## 6. 功能冒烟

⚠️ 快速确认：

- 模型中心能打开模型广场和已接入模型列表。
- 智能体工厂能打开。
- 知识库实验台能打开。
- 发布中心能打开。

本步不要求完整业务链路重测，但页面入口和基础交互必须可用。

## 7. 本步改动范围

本步改动：

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/src/layouts/MainLayout.vue`
- `frontend/src/styles/variables.css`
- `frontend/src/styles/index.css`
- `frontend/src/views/ModelHubView.vue`
- `docs/design/02-verify.md`

本步没有改：

- 路由 path
- API 调用
- 请求字段
- 后端接口
- 页面业务数据流
