# 00 UI Inventory：全局框架改造盘点

本文件是 UI/UX 改造第一批【全局框架】的 Step 0 盘点结果。当前步骤只做现状分析和施工计划，不改前端业务代码。

## 1. 前端现状

### 1.1 技术栈与 UI 组件库

结论：当前前端是 Vue 3 + Vite + Element Plus。

证据：

| 项 | 现状 | 文件证据 |
| --- | --- | --- |
| 框架 | Vue `3.5.13` | `frontend/package.json` |
| 构建 | Vite `6.0.7` | `frontend/package.json` |
| 路由 | Vue Router `4.5.0` | `frontend/package.json`、`frontend/src/router/index.ts` |
| 状态 | Pinia `2.3.0` | `frontend/package.json`、`frontend/src/stores/auth.ts` |
| UI 库 | Element Plus `2.9.1` | `frontend/package.json` |
| 图标 | `@element-plus/icons-vue` `2.3.1` | `frontend/package.json` |
| UI 注册 | `app.use(ElementPlus)` | `frontend/src/main.ts` |
| Element Plus CSS | `import 'element-plus/dist/index.css'` | `frontend/src/main.ts` |

### 1.2 样式组织

当前没有 `frontend/src/styles/` 目录，样式集中在一个全局文件：

- `frontend/src/styles.css`
- 入口：`frontend/src/main.ts` 中 `import './styles.css'`

现有 `styles.css` 已有一批基础变量，但还不是完整设计系统：

| 类型 | 当前情况 | 证据 |
| --- | --- | --- |
| spacing | `--space-1` 到 `--space-4`，值为 8/16/24/32px | `frontend/src/styles.css` |
| radius | `--radius-card: 12px` | `frontend/src/styles.css` |
| border | `--border-subtle`、`--border-strong` | `frontend/src/styles.css` |
| surface | `--surface-page`、`--surface-card` | `frontend/src/styles.css` |
| text | `--text-main`、`--text-muted` | `frontend/src/styles.css` |
| brand | `--brand-main` | `frontend/src/styles.css` |
| layout | `.app-shell`、`.sidebar`、`.main`、`.topbar` | `frontend/src/styles.css` |
| page/card | `.page-header`、`.panel-card`、`.task-card`、`.stat-card` 等 | `frontend/src/styles.css` |

问题：

- 样式变量不足，尚未按规范第四节形成完整 CSS Variables。
- 字体字号没有单独 typography 文件。
- Element Plus 覆盖散落在 `styles.css`，例如 `.topbar-actions .el-input__wrapper`、`.topbar-actions .el-button`、`.card-actions .el-button`。
- 页面组件还没有公共 `PageHeader / StatusTag / EmptyState / SectionHeader`。

### 1.3 当前主布局

主布局文件：`frontend/src/layouts/MainLayout.vue`

现状：

- 左侧 sidebar 为浅色背景，宽度由 `.app-shell { grid-template-columns: 280px minmax(0, 1fr); }` 控制。
- 导航项直接是单层 `navItems` 数组，没有分组。
- 顶部 topbar 左侧显示用户和租户，右侧显示搜索框和独立“退出”按钮。
- 图标来自 `@element-plus/icons-vue`，不是 Lucide 风格图标。

### 1.4 当前路由与页面清单

证据：`frontend/src/router/index.ts`

| 路由 path | 页面文件 | 当前显示入口 |
| --- | --- | --- |
| `/dashboard` | `DashboardView.vue` | 首页工作台 |
| `/agents` | `AgentListView.vue` | 智能体工厂 |
| `/model-hub` | `ModelHubView.vue` | 模型纳管 |
| `/templates` | `TemplateGalleryView.vue` | 模板广场 |
| `/kbs` | `KnowledgeBaseListView.vue` | 知识库实验台 |
| `/chat` | `ChatWorkbenchView.vue` | 调试对话 |
| `/publish` | `PublishCenterView.vue` | 发布中心 |
| `/tools` | `ToolsView.vue` | 工具中心 |
| `/workspaces` | `WorkspaceView.vue` | 当前有路由，但未出现在左侧菜单 |
| `/observability` | `ObservabilityCenterView.vue` | 观测中心 |
| `/audit` | `AuditLogView.vue` | 审计记录 |
| `/login` | `LoginView.vue` | 登录页，public route |

额外文件：

- `HomeView.vue` 存在，但当前路由没有使用。
- `WorkspaceView.vue` 有路由，但 `MainLayout.vue` 的 `navItems` 没有入口。

## 2. 对照 UI 标准的适配结论

`docs/design/ui-standard.md` 当前不存在。本盘点先按用户本轮明确描述的《统一UI/UX设计与前端改造标准V1.0》章节要求执行，后续用户补齐完整标准后再对照修订。

### 2.1 Element Plus 策略

当前项目已使用 Element Plus，因此规范第 27 节的 `el-*` 覆盖策略可以直接落地，不需要等价替换。

建议 Step 1 建立：

- `frontend/src/styles/variables.css`
- `frontend/src/styles/typography.css`
- `frontend/src/styles/element-plus.css`
- `frontend/src/styles/index.css`

然后在 `frontend/src/main.ts` 中用 `import './styles/index.css'` 替换现有 `import './styles.css'`。

### 2.2 设计变量策略

当前已有变量可以迁移，不建议推倒重写。

适配方式：

| 规范要求 | 当前状态 | Step 1 处理 |
| --- | --- | --- |
| 第四节 CSS Variables | 有少量变量，不完整 | 新建 `variables.css`，全量落地规范变量 |
| 第五节字体字号 | 只在 `:root` 配字体栈，没有字号体系 | 新建 `typography.css` |
| 第六节 4px 间距体系 | 当前是 8px 基础间距 | 在变量里补齐 4px scale，逐步替换 |
| 第七节卡片规范 | `.panel-card` 已有 12px radius、border、shadow | 保留类名，调整变量和阴影到规范 |
| 第九节 PageHeader | 当前各页散落 `.page-header` | Step 3 新建公共组件 |
| 第十四节 StatusTag | 当前直接用 `el-tag` | Step 3 新建封装组件 |
| 第十六节 EmptyState | 当前只有 `.empty` 文本样式 | Step 3 新建三要素组件 |
| 第 27 节 Element Plus 覆盖 | 覆盖散落在 `styles.css` | 收敛到 `element-plus.css` |

### 2.3 图标策略

当前使用 `@element-plus/icons-vue`。

规范要求 Step 2 使用统一 Lucide 风格线性图标 18px。建议：

- 引入轻量包 `lucide-vue-next`。
- 只在主布局导航先使用 Lucide，业务页面图标不在第一批中替换。
- 如果不想新增依赖，也可先用 Element Plus 图标近似替换，但这不完全满足“Lucide 风格”要求。

建议 Step 2 前确认是否允许新增 `lucide-vue-next`。若允许，需要修改 `frontend/package.json` 并重新安装依赖。

## 3. 现有导航与规范 8.1 分组映射

本次只映射现有页面，不新增未来功能入口，不改路由 path。

| 规范分组 | 现有页面 | 现有 path | Step 2 菜单显示名建议 | 备注 |
| --- | --- | --- | --- | --- |
| 工作台 | 首页工作台 | `/dashboard` | 首页工作台 | 保留 |
| 构建 | 智能体工厂 | `/agents` | 智能体工厂 | 保留 |
| 构建 | 模板广场 | `/templates` | 模板广场 | 保留 |
| 构建 | 调试对话 | `/chat` | 调试对话 | 保留 |
| AI资源 | 模型纳管 | `/model-hub` | 模型中心 | 建议显示名升级，path 不变 |
| AI资源 | 知识库实验台 | `/kbs` | 知识库实验台 | 保留 |
| AI资源 | 工具中心 | `/tools` | 工具中心 | 保留 |
| 运营 | 发布中心 | `/publish` | 发布中心 | 保留 |
| 运营 | 观测中心 | `/observability` | 观测中心 | 保留 |
| 管理 | 审计记录 | `/audit` | 审计记录 | 保留 |
| 管理 | 工作空间 | `/workspaces` | 工作空间 | 当前有路由但无菜单；本批次是否加入口需用户确认，默认不新增入口 |

未来预留，本次不加入口：

| 规范功能 | 本次处理 |
| --- | --- |
| 工作流 | 未来预留，本次不加入口 |
| Skills | 未来预留，本次不加入口 |
| 用量与费用 | 未来预留，本次不加入口 |
| 成员与权限 | 未来预留，本次不加入口 |

## 4. 本批次分步计划：全局框架

### Step 1：全局设计变量与基础样式

目标：

- 建立 `frontend/src/styles/` 体系。
- 迁移并扩展现有 `styles.css` 的变量。
- 全局字体栈、页面背景色、正文字号落地。
- 只做全局基础项，不逐页调细节。

预计改动文件：

- 新增 `frontend/src/styles/variables.css`
- 新增 `frontend/src/styles/typography.css`
- 新增 `frontend/src/styles/element-plus.css`
- 新增 `frontend/src/styles/index.css`
- 修改 `frontend/src/main.ts`
- 保留或迁移 `frontend/src/styles.css`
- 新增 `docs/design/01-verify.md`

验证方式：

- `cd frontend && npm run build`
- `docker compose up -d --build frontend`
- 浏览器打开 `http://localhost:18080`
- 检查整体字体、背景色变化。
- 逐个页面快速打开，无空白页、无控制台报错。

### Step 2：主布局与左侧导航

目标：

- 修改 `frontend/src/layouts/MainLayout.vue`。
- 深色侧边栏，宽度 232px。
- 导航项高度 40px。
- 按“工作台 / 构建 / AI资源 / 运营 / 管理”分组。
- 账户区移动到底部，退出登录放到账户菜单。
- 顶部栏精简，只保留当前页面上下文和搜索。
- Active 态使用蓝紫半透明背景。

预计改动文件：

- 修改 `frontend/src/layouts/MainLayout.vue`
- 修改 `frontend/src/styles/` 中布局相关样式
- 可能修改 `frontend/package.json`、`frontend/package-lock.json`：仅当确认引入 `lucide-vue-next`
- 新增 `docs/design/02-verify.md`

验证方式：

- `cd frontend && npm run build`
- `docker compose up -d --build frontend`
- ⚠️ 浏览器逐个点击所有菜单项，确认页面能打开：
  - `/dashboard`
  - `/agents`
  - `/model-hub`
  - `/templates`
  - `/kbs`
  - `/chat`
  - `/publish`
  - `/tools`
  - `/observability`
  - `/audit`
- ⚠️ 底部账户菜单能退出登录。

### Step 3：公共组件 + 模型纳管单页试点

目标：

- 新建公共组件：
  - `PageHeader`
  - `StatusTag`
  - `EmptyState`
  - `SectionHeader`
- 只试点改造 `ModelHubView.vue`。
- 不动 API 调用、请求字段、路由 path、数据流、业务逻辑。

预计改动文件：

- 新增 `frontend/src/components/common/PageHeader.vue`
- 新增 `frontend/src/components/common/StatusTag.vue`
- 新增 `frontend/src/components/common/EmptyState.vue`
- 新增 `frontend/src/components/common/SectionHeader.vue`
- 修改 `frontend/src/views/ModelHubView.vue`
- 修改 `frontend/src/styles/` 中 card/button/tag 相关样式
- 新增 `docs/design/03-verify.md`

验证方式：

- `cd frontend && npm run build`
- `docker compose up -d --build frontend`
- ⚠️ 浏览器打开 `/model-hub` 看试点效果：
  - 标题结构是否统一
  - 状态标签颜色是否规范
  - 按钮高度和主次是否清楚
  - 卡片圆角、边框、阴影、间距是否统一
- ⚠️ 模型纳管原功能逐个验证：
  - 模型广场展示
  - 一键接入弹窗
  - mock 接入成功
  - 错误 key 友好提示
  - 启停模型
  - 查看渠道
  - 重新测试渠道

## 5. Step 0 结论

1. 当前项目已经使用 Element Plus，不需要改 UI 框架。
2. 当前样式集中在单个 `styles.css`，需要拆成设计系统目录。
3. 主布局和导航目前是浅色、单层菜单，和规范目标差距集中在 Step 2。
4. 公共组件体系缺失，适合 Step 3 先在 `ModelHubView.vue` 做试点。
5. `docs/design/ui-standard.md` 当前缺失，后续用户补齐完整标准后，需要再次核对变量命名、颜色值、字号和状态色是否完全一致。
