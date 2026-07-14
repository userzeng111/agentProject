# 聊天移动端可访问性与章节索引写入 warning 设计

## 背景

当前 active 仍有两条主线：

- UI/UX：阶段 4 暗黑模式全页面精调、移动端布局、可访问性与大组件拆分仍需继续推进。
- MVP 审查：运行时死代码与关键异常 warning 覆盖仍需继续分低风险批次清理。

本批只做两个互不依赖的小切片：聊天页消息区移动端可访问性与长文本溢出兜底，以及章节写入时读取 `chapters/index.json` 的 warning 与格式防护。两者不改流式聊天协议、会话持久化、模型验证状态机、StoryEngine、动态 Agent、恢复状态机或 TaskLogStore 共享存储逻辑。

## 设计范围

### 聊天页消息区移动端可访问性与溢出兜底

目标文件：

- `apps/web/src/features/chat/chat-client.tsx`
- `apps/web/e2e/chat-settings.spec.ts`

当前聊天页有几个低风险但实际影响体验的问题：

- 移动端菜单图标按钮缺少可访问名称。
- 思考过程区域使用可点击 `Box`，缺少 `button` 语义、`aria-expanded` 和键盘操作。
- 用户/助手消息气泡与正文没有统一长文本断词，超长 URL 或模型输出可能造成 390px 移动端横向溢出。
- 消息滚动区只有 `overflowY`，缺少 `overflowX: "hidden"` 的页面级兜底。
- 消息滚动条颜色存在硬编码浅色残留，暗色模式下不够一致。

本批将：

- 给移动端会话菜单按钮补 `aria-label="打开会话列表"`。
- 将思考过程触发区改为语义按钮或等价可访问控件，提供 `aria-expanded`、`aria-controls` 与键盘 Enter/Space 展开收起能力。
- 给消息气泡、正文和思考内容补 `minWidth: 0`、`overflowWrap: "anywhere"`、`wordBreak: "break-word"` 等稳定尺寸约束。
- 给消息滚动区补 `minWidth: 0`、`overflowX: "hidden"`，并用 theme mode 派生滚动条颜色。
- 保留流式响应、思考链折叠状态、会话存储、RAG 提示、模型选择和模型验证入口行为。

测试策略：

- 扩展 `chat-settings.spec.ts`，新增 390px 移动端用例。
- 用长不可断用户输入、长不可断回复和思考链内容触发潜在横向溢出，断言 `document.documentElement.scrollWidth <= window.innerWidth`。
- 断言思考过程可以通过 role button 定位，`Enter` 或 `Space` 可切换 `aria-expanded`。
- 保留现有聊天流式响应 E2E 作为行为回归。

### 章节索引写入 warning 与格式防护

目标文件：

- `apps/agent-runtime/app/application/task_service/continuation.py`
- `apps/agent-runtime/tests/test_recovery_chapter_progress.py`

当前 `get_current_chapters()` 读取侧已经对损坏章节索引有 warning，但 `_write_chapter_file()` 写入侧仍有缺口：

- 读取旧 `chapters/index.json` 时只捕获 JSON 解析异常，没有捕获 `OSError`。
- 损坏 JSON 时静默重置索引，缺少 warning。
- 顶层不是 list、条目不是 dict 或 `number` 非正整数时，可能在 `item.get("number")` 或排序处抛错，导致章节正文已写入但索引更新失败。

本批将：

- 抽出或局部实现写入侧索引规范化逻辑。
- `index.json` 读取/解析失败时记录 `读取章节索引失败 task_id=%s path=%s` warning，并以空索引重建当前章节。
- `index.json` 顶层不是 list 时记录 `章节索引格式不正确 task_id=%s path=%s` warning，并以空索引重建当前章节。
- index 条目不是 dict，或 `number` 不是正整数、为 bool、为非正整数时记录 `章节索引条目格式不正确 task_id=%s path=%s` warning，并跳过坏条目。
- 当前写入章节始终落盘到 `.md` / `.json`，且 `index.json` 至少包含当前章节。

测试策略：

- 构造损坏 `chapters/index.json` 后调用 `_write_chapter_file()`，断言 warning、当前章节文件存在、索引重建且 `get_current_chapters()` 能读回当前章节。
- 构造非 list `index.json`，断言 warning 且当前章节索引正常落盘。
- 构造坏条目与有效条目混合的 index，断言坏条目 warning、有效条目保留、当前章节追加并排序稳定。

## 不在本批处理

- 不拆 `ChatClient` 大组件。
- 不改 `streamChat()`、`streamModelValidation()` 或模型验证状态机。
- 不改 `ModelValidationPanel` 移动端布局。
- 不做全站暗色模式一次性扫尾。
- 不碰 `StoryEngine.generate_chapter_pair()`、动态 Agent、自动审核桥接或 `TaskLogStore`。
- 不处理 `recovery.py` 中恢复路径读取章节 JSON 的异常策略或 `md_ref` 疑点。

## 验收标准

- 聊天页 390px 移动端长文本和思考链不造成横向滚动。
- 思考过程折叠控件具备按钮语义、可访问名称、`aria-expanded` 和键盘切换能力。
- 移动端会话菜单按钮具备可访问名称。
- `_write_chapter_file()` 遇到损坏、格式错误或坏条目的章节索引时记录 warning，并能安全写入当前章节索引。
- 目标 E2E、前端测试/lint/build、后端 ruff/pytest 与全量 E2E 通过。
- active worklog 更新；主线仍未完整完成则不归档。
