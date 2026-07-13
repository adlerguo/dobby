# wanwu 补丁登记

本文件登记阶段 1 起所有对 `wanwu/` 目录的修改。升级 wanwu 时先合并上游，再按本文件逐项重放和验证。

## 阶段 1：cockpit-service 接入

### 1. nginx 增加 cockpit 反向代理

- 文件：`wanwu/configs/middleware/nginx/conf.d/aibase.conf`
- 修改内容：

```diff
+    location ^~ /cockpit/api/ {
+        proxy_pass       http://cockpit-service:18081/api/;  # 智能体驾驶舱增量服务
+        proxy_buffering  off;                                # 关闭缓冲，支持阶段2评测SSE流式透传
+        proxy_cache      off;
+        proxy_read_timeout 3600s;
+    }
```

- 原因：让 wanwu 前端通过同一个 nginx 入口访问 cockpit-service；cockpit-service 不暴露宿主机端口。
- 升级重放：在 `server` 块后端 API 代理区域重新插入该 `location`，确认 `proxy_pass` 指向 `cockpit-service:18081/api/`。

### 2. 前端权限常量增加 cockpit

- 文件：`wanwu/web/src/router/constants.js`
- 修改内容：

```diff
+  COCKPIT: 'cockpit', // 智能体驾驶舱
```

- 原因：为后续 IAM 权限点预留稳定常量。
- 升级重放：在 `PERMS` 导出对象中追加 `COCKPIT`。

### 3. 前端路由增加 `/cockpit`

- 文件：`wanwu/web/src/router/index.js`
- 修改内容：

```diff
+      {
+        path: '/cockpit',
+        component: resolve => require(['@/views/cockpit'], resolve),
+        meta: { perm: [PERMS.COCKPIT], publicForLogin: true },
+      },
...
+  if (route.meta?.publicForLogin) return true;
```

- 原因：注册驾驶舱页面。阶段 1 尚未接入 IAM 权限点，临时允许所有登录用户访问。
- 升级重放：在 `/portal` children 下添加路由，并保留 `publicForLogin` 过渡逻辑。阶段 7 接入 IAM 后删除 `publicForLogin`。

### 4. 前端菜单增加“驾驶舱”

- 文件：`wanwu/web/src/views/layout/menu.js`
- 修改内容：

```diff
+  {
+    name: '驾驶舱',
+    index: 'cockpit',
+    icon: 'menu_statistics',
+    path: '/cockpit',
+  },
```

- 原因：阶段 1 要完成“前端菜单 → nginx → cockpit → 数据库”链路验证。由于后端权限数据尚无 `cockpit` 权限点，本阶段使用前端硬编码让所有登录用户可见。
- 升级重放：在 `menuList` 末尾追加该菜单项。TODO：阶段 7 接入 IAM 权限点后改为 `perm: PERMS.COCKPIT` 或放入正式菜单组。

### 5. 新增 cockpit API 封装

- 文件：`wanwu/web/src/api/cockpit.js`
- 修改内容：新增独立 axios 实例，`baseURL` 为 `${basePath}/cockpit/api`，请求头注入 `Authorization: Bearer <token>`、`x-org-id`、`x-client-id`。
- 原因：wanwu 默认 `utils/request.js` 走 `/service/api`，cockpit 走 nginx 直通 `/cockpit/api`，不能复用默认 baseURL。
- 升级重放：如该文件丢失，按本阶段版本恢复。

### 6. 新增 cockpit 占位页

- 文件：`wanwu/web/src/views/cockpit/index.vue`
- 修改内容：新增驾驶舱链路验证页，调用 `/v1/health` 与 `/v1/me`，展示服务状态、版本、`user_id`、`org_id`。
- 原因：用于阶段 1 浏览器验收。
- 升级重放：如该目录丢失，按本阶段版本恢复。

## 阶段 2：评测与经验库入口

### 1. cockpit API 封装扩展

- 文件：`wanwu/web/src/api/cockpit.js`
- 修改内容：在阶段 1 独立 axios 实例上新增 assistant 代理、评测用例、评测运行、经验库 CRUD 方法。
- 原因：前端仍只访问 cockpit 后端，由 cockpit 后端代理 wanwu BFF，避免前端直连拼装评测调用。
- 升级重放：恢复 `fetchCockpitAssistants`、`fetchEvalCases`、`createEvalCase`、`updateEvalCase`、`deleteEvalCase`、`createEvalRun`、`fetchEvalRuns`、`fetchEvalRun`、`fetchEvalRunProgress`、`fetchExperiences`、`createExperience`、`updateExperience`、`deleteExperience`。

### 2. cockpit 页面改为子导航布局

- 文件：`wanwu/web/src/views/cockpit/index.vue`
- 修改内容：阶段 1 链路验证页改为 `el-tabs`，包含“链路验证 / 评测管理 / 经验库”三个页签。
- 原因：阶段 2 需要在同一一级菜单下承载评测与经验库功能。
- 升级重放：恢复该页面，并确保仍调用 `/v1/health` 与 `/v1/me` 作为链路验证。

### 3. 新增评测管理组件

- 文件：`wanwu/web/src/views/cockpit/components/EvalPanel.vue`
- 修改内容：新增用例表格、创建/编辑用例弹窗、发起评测、运行记录、运行详情抽屉。
- 原因：完成“创建用例 → 发起评测 → 查看 item 指标”的阶段 2 前端入口。
- 升级重放：恢复该组件；若后续 IAM 权限点接入，只调整路由/菜单权限，不改变该组件 API 约定。

### 4. 新增经验库组件

- 文件：`wanwu/web/src/views/cockpit/components/ExperiencePanel.vue`
- 修改内容：新增经验库表格、关键词搜索、新增/编辑/删除弹窗。
- 原因：迁移 legacy Experience 的增删改查与关键词检索能力。
- 升级重放：恢复该组件。
