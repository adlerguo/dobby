# 统一 UI/UX 设计与前端改造标准 V1.0

本标准作为 `6qiyeagent` 后续所有 UI 工作的统一依据。当前版本先落地本项目已确认的全局框架、设计变量、布局、导航、组件和 Element Plus 覆盖策略；后续如补充更完整的视觉稿或品牌规范，以本文件增量修订为准。

## 1. 目标

- 将界面从功能 demo 提升为正式企业级 AI SaaS 工作台。
- 统一布局、间距、卡片、按钮、状态、导航和页面标题结构。
- 优先保证业务功能不受影响，不改变 API、路由 path、请求字段和数据流。
- 通过小步试点方式逐批推进，先建立设计系统，再铺开页面。

## 2. 产品气质

- 安静、专业、清晰、可重复使用。
- 面向企业管理者、业务运营、AI 应用构建者和技术管理员。
- 不做营销式大 hero，不做花哨装饰，不用大面积单色渐变。
- 工作台界面优先信息密度、扫描效率和操作确定性。

## 3. 技术原则

- 保持 Vue 3 + Vite + Element Plus。
- 不引入第二套 UI 框架。
- 图标统一向 Lucide 风格线性图标演进，第一批仅用于主布局导航。
- 所有全局样式进入 `frontend/src/styles/` 体系。
- 公共组件进入 `frontend/src/components/common/`。

## 4. CSS Variables

全局变量必须集中定义，禁止页面内随意硬编码新的色值、圆角和间距。

```css
:root {
  --color-bg-page: #F5F7FA;
  --color-bg-card: #FFFFFF;
  --color-bg-sidebar: #111827;
  --color-bg-sidebar-active: rgba(99, 102, 241, 0.16);
  --color-bg-muted: #F3F4F6;

  --color-text-primary: #111827;
  --color-text-secondary: #4B5563;
  --color-text-tertiary: #6B7280;
  --color-text-inverse: #FFFFFF;

  --color-border-subtle: #E5E7EB;
  --color-border-strong: #D1D5DB;

  --color-brand-primary: #2563EB;
  --color-brand-secondary: #6366F1;
  --color-brand-hover: #1D4ED8;

  --color-success: #16A34A;
  --color-warning: #F59E0B;
  --color-danger: #DC2626;
  --color-info: #2563EB;
  --color-neutral: #6B7280;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;

  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-pill: 999px;

  --shadow-card: 0 1px 2px rgba(16, 24, 40, 0.04);
  --shadow-popover: 0 12px 32px rgba(15, 23, 42, 0.12);
}
```

兼容旧类名期间，可保留 `--surface-page`、`--surface-card`、`--text-main`、`--text-muted`、`--brand-main`、`--radius-card`、`--border-subtle` 等别名，但值必须映射到新变量。

## 5. 字体与字号

- 字体栈：`Inter, PingFang SC, Microsoft YaHei, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
- 正文默认：14px / 1.6
- 页面标题：24px / 1.25 / 700
- 区块标题：18px / 1.35 / 700
- 卡片标题：16px / 1.4 / 700
- 辅助文本：13px / 1.5
- 表格和表单默认维持 14px。

## 6. 间距体系

采用 4px spacing system。

- 4px：极小间距
- 8px：小间距
- 12px：紧凑表单内间距
- 16px：常规组件间距
- 20px：卡片内边距
- 24px：区块间距
- 32px：页面大区块间距

页面内容区不贴边，模块之间不拥挤，也不出现局部过度空旷。

## 7. 卡片规范

默认卡片：

- `background: #FFFFFF`
- `border: 1px solid #E5E7EB`
- `border-radius: 12px`
- `padding: 20px 或 24px`
- `box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04)`

卡片内标题、描述、标签、操作区必须层级清楚。重复卡片同一行高度、宽度、按钮位置尽量一致。

## 8. 主导航

### 8.1 分组

第一批主导航分组：

- 工作台
- 构建
- AI资源
- 运营
- 管理

只放已有真实页面。未来功能如工作流、Skills、用量与费用、成员与权限，本批次不加入口。

### 8.2 侧边栏

- 背景：`--color-bg-sidebar #111827`
- 宽度：232px
- 导航项高度：40px
- 图标：18px 线性图标
- Active：蓝紫半透明背景
- 账户区固定在底部，退出登录放入账户菜单

## 9. PageHeader

页面头部统一为：

- 标题
- 一句话说明
- 右侧主操作区

页面标题区不写过长解释，不堆多个按钮。按钮主次要明确。

## 10. 表格

- 表头清晰、行高稳定。
- 操作列靠右，宽度稳定。
- 不在表格里回显密钥、token 或敏感字段。

## 11. 表单

- 必填项清楚。
- 密钥字段统一使用 password 输入框。
- 错误信息用用户能理解的语言，不直接暴露后端堆栈或原始对象。

## 12. 按钮

- 默认高度 36px。
- 主操作使用 primary。
- 次操作使用 default/plain。
- 危险操作必须使用 danger 或二次确认。

## 13. 标签

标签用于状态、类型、来源和能力，不用于承载长文本。

## 14. StatusTag

状态色统一：

- success：成功、启用、已发布、健康
- warning：待处理、需配置、规划中
- danger：失败、错误、停用风险
- info：运行中、处理中
- neutral：停用、未知、草稿

状态标签采用胶囊形态。

## 15. 加载与反馈

- 请求中必须有 loading 状态。
- 成功用轻提示。
- 可恢复失败在弹窗或表单内显示，不直接关闭用户上下文。

## 16. EmptyState

空状态由三要素组成：

- 标题
- 一句话说明
- 一个主操作或明确下一步

禁止只显示“暂无数据”。

## 17. 搜索

全局搜索位于顶部栏。页面内搜索靠近对应列表或卡片区域。

## 18. 响应式

第一批以桌面工作台为主，但不能在窄屏下出现文本严重溢出或操作不可达。

## 19. 安全显示

任何 API Key、密钥明文、密钥 hash、加密字段不得在页面列表、详情、抽屉、日志中显示。

## 20. 可访问性

- 按钮必须有明确文本或 tooltip。
- 活跃态不能只依赖颜色。
- 表单错误需要文本提示。

## 21. 页面内容组织

工作台页面按用户任务组织，而不是后台模块堆叠。业务页面第一屏应直接呈现可用工作内容。

## 22. 数据看板

专业视图和领导视图应使用更贴近产品语义的命名，避免直白技术词堆砌。

## 23. 模型中心

模型广场并入模型中心，不单列菜单。一键接入必须先测试连接，通过后再启用；错误 key 不得留下僵尸渠道。

## 24. 知识库

检索结果必须展示正文片段、来源文档、分数和引用信息。

## 25. 发布中心

API Key 明文只展示一次，后续只显示 prefix。

## 26. 渐进改造

每批只做明确边界。第一批只做设计系统、主布局、公共组件和单页试点。

## 27. Element Plus 覆盖策略

Element Plus 作为基础组件库保留，通过全局覆盖统一视觉。

覆盖入口：

- `frontend/src/styles/element-plus.css`

覆盖范围：

- Button 高度、圆角、字体
- Input 高度、圆角、边框
- Select 与 Input 对齐
- Tag 胶囊样式
- Table 表头、边框、行高
- Dialog 圆角和标题
- Drawer 圆角和内边距
- Alert 文案尺寸

禁止在各页面散落新的 `el-*` 覆盖，确需页面局部调整时应先评估是否抽成公共组件或全局规则。
