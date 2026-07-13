# 01 Verify：全局设计变量与基础样式

本步只建立全局样式体系，不改 API、路由 path、请求字段和业务逻辑。

## 1. 构建验证

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent/frontend
npm run build
```

期望：`vue-tsc --noEmit && vite build` 成功。

## 2. 镜像重建

前端样式已重新构建进 `dist`，真机验证前需要重建 frontend 镜像：

```bash
cd /Users/wangsiyi/LocalDocuments/codexxxx/6qiyeagent
docker compose up -d --build frontend
```

如果 backend/maas/postgres 已经在运行，不需要重启它们。

## 3. 浏览器验证

打开：

```text
http://localhost:18080
```

如页面已打开，请按 `Cmd+Shift+R` 强制刷新。

检查项：

- 页面背景应使用新变量 `--color-bg-page: #F5F7FA`。
- 全局字体应使用 `Inter + PingFang SC + Microsoft YaHei + system-ui` 字体栈。
- 正文默认字号为 14px。
- Element Plus 按钮、输入框、表格、标签的圆角和基础高度不应出现异常。
- 原有页面卡片、统计卡片、表格、弹窗、抽屉仍应保持可用。

## 4. 逐页打开验证

⚠️ 逐个打开以下页面，确认无空白页、无明显样式断裂、无控制台报错：

- `/dashboard`
- `/agents`
- `/model-hub`
- `/templates`
- `/kbs`
- `/chat`
- `/publish`
- `/tools`
- `/workspaces`
- `/observability`
- `/audit`

## 5. 功能冒烟

⚠️ 不需要完整业务回归，但至少确认：

- 登录后仍能进入首页。
- 左侧菜单点击仍可切换页面。
- 模型中心页面能正常显示模型广场和已接入模型。
- 任意一个弹窗或抽屉能正常打开和关闭。

## 6. 本步改动范围确认

本步只改：

- `docs/design/ui-standard.md`
- `frontend/src/styles/variables.css`
- `frontend/src/styles/typography.css`
- `frontend/src/styles/element-plus.css`
- `frontend/src/styles/index.css`
- `frontend/src/main.ts`

本步不改：

- API 调用
- 请求字段
- 路由 path
- 业务数据流
- 主布局结构
