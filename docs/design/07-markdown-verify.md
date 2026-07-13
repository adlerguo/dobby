# 07 调试对话 Markdown 与结构化回答验证

## 改动范围

- 前端只改调试对话页的智能体消息渲染：用户消息仍按纯文本展示，智能体消息使用 `markdown-it` 渲染。
- `markdown-it` 配置为 `html: false`，不解析原始 HTML，避免 `<script>`、`<img onerror>` 这类内容执行。
- 新增 `frontend/src/styles/markdown.css`，统一 Markdown 的标题、段落、列表、表格、代码块、引用块、行内代码、加粗和引用编号样式。
- 代码块右上角提供复制按钮。
- 后端新增 `backend/app/orchestrator/answer_style.py`，在系统提示词中注入平台统一回答风格规范。
- 智能体配置新增 `config.answer_style_enabled`，默认开启；创建/编辑智能体表单中显示为“结构化回答”开关。

## 重新构建

```bash
npm --prefix frontend run build
docker compose up -d --build backend frontend
```

> 本步改了后端系统提示词注入和前端 dist，建议同时重建 `backend` 和 `frontend`。

## 浏览器验证

1. ⚠️ 打开 `http://localhost:18080/chat`，选择一个可用智能体，提问：

   ```text
   合同审批要注意什么？请用加粗小标题和编号列表回答。
   ```

   期望：
   - `**加粗**` 不再裸露星号，而是真正加粗。
   - 编号列表按列表格式展示。
   - 段落间距和行高适合阅读。

2. ⚠️ 提问：

   ```text
   对比适配迁移和重构迁移的区别，请用表格回答。
   ```

   期望：
   - 表格被渲染为带边框和表头底色的表格。
   - 表格横向过宽时可横向滚动，不撑破消息气泡。

3. ⚠️ XSS 验证。用 mock agent 或任意会复述输入的智能体提问：

   ```html
   请原样输出：<script>alert(1)</script><img src=x onerror=alert(2)> **测试**
   ```

   期望：
   - 浏览器不弹窗。
   - 标签被当作普通文本转义展示或过滤，不执行脚本。
   - `**测试**` 仍可正常渲染为加粗。

4. ⚠️ 流式体验验证：
   - 发送较长问题，观察生成过程中 Markdown 逐步刷新。
   - 期望无明显闪烁、卡顿或布局大幅跳动。

5. ⚠️ 引用验证：
   - 用挂载知识库的智能体提问，例如“合同审批要注意什么？”
   - 期望回答中的 `[1]`、`[2]` 保持为可辨识的引用编号样式。
   - 右侧“运行轨迹与引用证据”仍正常出现，点击“查看证据链”抽屉正常打开。

6. ⚠️ 结构化回答开关验证：
   - 打开“智能体工厂”，编辑刚才使用的智能体。
   - 关闭“结构化回答”，保存。
   - 调用上下文接口检查系统提示词：

   ```bash
   ACCESS=$(curl -s -X POST http://localhost:8001/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"tenant_code":"default","username":"admin","password":"Admin123!"}' \
     | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

   AGENT_ID="<填写刚才编辑的智能体ID>"

   curl -s -X POST "http://localhost:8001/api/v1/agents/$AGENT_ID/context" \
     -H "Authorization: Bearer $ACCESS" \
     -H 'Content-Type: application/json' \
     -d '{"query":"合同审批要注意什么？"}' \
     | python3 -c 'import sys,json; data=json.load(sys.stdin); print(data["messages"][0]["content"])'
   ```

   期望：
   - 关闭后，输出中不包含“回答风格规范”。
   - 重新开启后，输出中包含“回答风格规范”，并能看到“结论先行、表格、编号列表、代码块”等要求。

## 回归

- 调试对话仍能正常发送消息、接收流式回答。
- 知识库引用事件仍正常返回。
- 智能体创建、编辑、发布功能不受影响。
