# 归档阅读器与 RAG 状态日志 Design

## 背景

当前 active 主线仍有两类未完成事项：

- UI/UX 阶段 3/4：审核页/结果页已接入 `ProjectShell` 与 `StageNav`，但归档详情仍使用旧页面壳；结果页没有按章阅读器；归档详情局部阅读器存在浅色硬编码，暗色模式下可读性不足。
- MVP 审查后续：前三批低风险日志与缓存清理已完成，下一批适合继续补一处低风险、行为不变的异常日志覆盖。

并行审计结论显示，当前不适合一次性重构 `/p/[projectId]` 工作台、审核页完整左右分屏、动态 Agent 栈或 `TaskLogStore` 恢复链路。下一批应选择可测试、文件范围有限、能直接推进 active 目标的切片。

## 目标

完成一个阶段 3/4 交叉的 UI 切片，并补一个低风险后端日志切片：

1. 保留并验证 `StageNav` 在阶段没有传 `icon` 时的数字兜底，防止空圆点回归。
2. 新增共享 `NovelReader`，让结果页和归档详情共用按章阅读体验。
3. 归档详情接入 `ProjectShell`，去掉旧面包屑/标题壳，保留 Tab、复制、导出和 query tab 同步行为。
4. 归档阅读器移除浅色硬编码，使用主题 token，兼容暗色模式。
5. `NovelCorpusRebuildService._load_status()` 在 status JSON 存在但读取/解析失败时记录 warning，继续返回 `None`，不改变接口语义。

## 非目标

- 不迁移 `/archive/detail?id=`、`/result?id=` 路由。
- 不改归档列表整体作品库样式。
- 不做审核页完整左右分屏。
- 不删除 test-only 通用组件；这些组件后续 UI 切片可能复用，先不引入 churn。
- 不触碰 `TaskLogStore`、动态 Agent、`StoryEngine` 主链路。

## 前端设计

### `NovelReader`

新增 `apps/web/src/components/novel-reader.tsx`，职责限定为“章节阅读”：

- 输入 `chapters: ResultChapterItem[]`。
- 内部维护当前页码，支持上一章、下一章、分页跳转。
- 使用 `Paper`、`Stack`、`Pagination`、`MarkdownContent`。
- 根节点设置 `data-testid="novel-reader"`，章节正文区域设置 `data-testid="novel-reader-content"`。
- 空章节返回 info `Alert`，不抛错。
- 样式使用 `background.default`、`background.paper`、`text.primary`、`divider` 等主题 token，不再使用 `#fffaf2`、`#1d2a27`。
- 导航区域按钮在移动端可换行，避免横向滚动；正文容器 `minWidth: 0`，长词交给 `MarkdownContent` 和容器断词处理。

### 结果页

`TaskResultClient` 不再只展示整篇 Markdown 卡片，而是增加按章阅读器：

- `result.chapter_index` 有内容时，展示 `NovelReader` 作为主要阅读体验。
- 仍保留“正文内容”整篇 Markdown 卡片和“复制全文/导出 MD”操作，避免用户失去全文导出工作流。
- 原“章节索引”卡片保留，用于查看章节文件与摘要，不改变现有可见内容。
- `StageNav` 继续使用无 icon 数据，由组件兜底数字，降低调用方负担。

### 归档详情

`ArchiveDetailClient` 接入 `ProjectShell`：

- 面包屑：`首页 / 归档 / {标题}`。
- 标题：`归档详情`。
- meta：标题、类型、默认模型、最近动作模型。
- actions：返回列表、结果页视图。
- 原 Tab 保持 `overview | outline | read | meta`，`tab` query 同步逻辑不变。
- `read` Tab 使用共享 `NovelReader`。
- `Snackbar` 保留在 `ProjectShell` 内部末尾，不改变复制/导出反馈。

## 后端设计

`NovelCorpusRebuildService._load_status()` 当前在 status 文件存在但 JSON 读取失败时静默返回 `None`。本批只增加 warning：

- 文件不存在：继续静默返回 `None`。
- 文件存在但读取失败、JSON 解析失败或内容不是对象：记录 warning，返回 `None`。
- `get_status()` 的 `last_result` 仍为 `None`，接口结构不变。

## 测试设计

### RED

- `stage-nav.test.mjs`：SSR 渲染没有 icon 的 `StageNav`，断言当前阶段圆点显示步骤数字。该回归测试已先行完成，后续保持通过。
- `novel-reader.test.mjs`：断言页码 clamp、空章节状态，以及 SSR 渲染输出不包含旧归档阅读器硬编码颜色 `#fffaf2`、`#1d2a27`。
- `review-result-archive.spec.ts`：结果页断言 `novel-reader` 可见，点击“下一章”后显示第二章；同时断言“复制全文”“导出 MD”仍可见，点击复制后出现反馈。
- `review-result-archive.spec.ts`：归档详情断言 `project-shell` 可见；访问 `tab=read` 时 `novel-reader` 可见；点击 Tab 后 URL query 更新；Meta Tab 中“复制全文”“导出 MD”仍可见，点击复制后出现反馈。
- 后端 `test_rag_rebuild.py`：分别构造损坏 status JSON 与“可解析但不是对象”的 status JSON，调用 `get_status()`，断言 `last_result is None` 且记录 warning。

### GREEN

- 实现 `NovelReader` 并接入结果页、归档详情。
- `StageNav` 对缺失 icon 使用 `index + 1` 兜底，并保持回归测试通过。
- `_load_status()` 补 warning。

### 汇总验证

- `npm --prefix apps/web test`
- `npm --prefix apps/web run lint`
- `npm --prefix apps/web run build`
- `npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium`
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_rag_rebuild.py -q`
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`
- 汇总阶段再跑前后端全量或项目 smoke，按改动范围决定。

## 风险

- 归档详情壳迁移可能影响标题、按钮和 Tab 定位；用 E2E 覆盖。
- 共享阅读器必须保持归档阅读章节翻页行为；用归档详情 `tab=read` E2E 覆盖。
- 结果页新增阅读器不能替代全文导出；复制/导出仍留在正文卡片内。
- 暗色模式目标不能只靠人工检查；`NovelReader` 单测至少证明旧硬编码颜色不再进入渲染输出。
- RAG warning 不能对 status 文件不存在场景刷日志；测试覆盖损坏文件存在与 JSON 非对象两种异常输入。
