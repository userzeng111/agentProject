# 归档列表体验与上下文缓存日志 Design

## 背景

当前 active 主线仍有两类未完成事项：

- UI/UX 阶段 3/4：归档详情和结果阅读器已完成，但归档列表仍是旧式单列卡片，信息密度低，移动端长标题/模型字段缺少稳定断词约束。
- MVP 审查后续：模型、RAG 等低风险日志覆盖已推进多批；上下文缓存与磁盘缓存已有 warning 分支，但测试主要覆盖功能回退，没有验证日志是否真的出现。

并行审计结论显示，审核页左右分屏、`TaskRunClient` 拆分、全站暗黑模式和动态 Agent/StoryEngine 都不适合混入本批。本批选择边界清晰、行为可测的切片。

## 目标

1. 归档列表升级为更接近首页作品库的项目卡片体验。
2. 归档卡片显示可扫描的归档指标：章节数、字数、类型、模型、更新时间。
3. 归档列表在桌面和移动端都不能产生页面级横向滚动，长任务标题和长模型 ID 必须断词。
4. 保留现有 `/archive/detail/?id=...` 路由；归档列表 API 仅允许向 `TaskSummary` 增加向后兼容的可选指标字段。
5. 给上下文缓存和磁盘缓存的异常降级路径补日志断言测试，保持业务返回语义不变。

## 非目标

- 不改归档详情页结构。
- 不新增归档筛选、搜索、排序或后端查询参数。
- 不做审核页左右分屏。
- 不拆 `TaskRunClient`、`TaskReviewClient` 大组件。
- 不删除 test-only 前端组件；前端死代码清理留到独立批次。
- 不触碰动态 Agent、`StoryEngine`、`TaskLogStore` 恢复链路。

## 前端设计

### 归档列表页面

`ArchiveListClient` 仍负责数据加载、分页和错误展示。视觉层调整为：

- 页面标题保留“归档任务”，副文案改为强调“已完成作品库”。
- 列表卡片增加 `data-testid="archive-card"`，卡片内分为标题摘要、指标 chip、模型/时间信息、主操作。
- 指标包括：
  - `章节：{chapter_count ?? 0}`
  - `字数：{word_count ?? 0}`
  - 类型：沿用 `formatTaskTypeLabel()`
  - 模型：`default_model_id || model_id || "默认模型"`
  - 最近动作模型：仅存在时显示
  - 更新时间：`toLocaleString("zh-CN")`
- 主操作保持 `archiveDetailHref(item.task_id)`，文案为“查看归档详情”。
- loading skeleton 保留，但使用主题 token。
- 空态保留信息提示和返回首页入口。

### 响应式与可访问性

- 卡片、标题、摘要、chip label 和模型字段都设置 `minWidth: 0` 与 `overflowWrap: "anywhere"`。
- 卡片底部操作在移动端纵向排列，桌面横向排列。
- 分页保持居中，`aria-label` 使用 MUI Pagination 默认语义即可。
- 不使用 emoji 图标，不新增装饰性图形。

## 归档 API 设计

`ArchiveTaskListResponse.items` 继续复用 `TaskSummary`。为避免前端只依赖 mock 字段，本批在 `TaskSummary` 增加两个可选字段：

- `chapter_count: int | None = None`：归档任务优先取 `draft_result.chapters` 数量；没有正文结果时回退到 `story_plan.chapter_plan` 数量；仍缺失则为 `None`。
- `word_count: int | None = None`：归档任务优先统计 `draft_result.chapters[*].content` 的近似字数；没有正文时为 `None`。

该扩展是向后兼容字段，不改变现有字段含义。仪表盘和工作台如果也拿到字段，可忽略；归档列表会使用它们展示指标。

## 后端设计

本批后端分两部分：

- API contract：为 `TaskSummary` 和 `_to_summary()` 增加归档指标字段。
- 日志覆盖：优先新增 characterization tests；如果测试暴露日志缺失，再做最小实现。

覆盖对象：

- `ContextManager.build_snapshot()`：
  - `cache_store.get()` 抛异常时，返回新 snapshot，并记录“读取上下文缓存失败”。
  - `cache_store.set()` 抛异常时，仍返回新 snapshot，并记录“写入上下文缓存失败”。
- `FileBackedCacheStore.get()`：
  - 磁盘 JSON 损坏时返回 `None`，并记录“读取磁盘缓存失败”。
- `LayeredCacheStore`：
  - 某层 `get()` 抛异常时继续读取后续层，并记录“缓存层读取失败”。
  - 某层 `set()` 抛异常时继续写入其他层，并记录“缓存写入失败”。

## 测试设计

### RED

- `review-result-archive.spec.ts`：
  - 归档列表 fixture 提供长标题、长模型 ID、`chapter_count`、`word_count`。
  - 桌面断言 `archive-card` 可见，显示章节数、字数、类型、模型、更新时间和详情链接。
  - 移动端 390px 访问 `/archive`，断言 `document.documentElement.scrollWidth <= clientWidth`。
  - 空态仍可渲染。
- `test_api_context.py`：
  - 完成任务归档后，调用 `/api/archive`。
  - 断言列表项包含真实 `chapter_count` 和 `word_count`。
- `test_context_manager.py`：
  - 使用抛异常 cache store，断言 `ContextManager` 读缓存失败 warning。
  - 使用抛异常 cache store，断言 `ContextManager` 写缓存失败 warning。
  - 新增或扩展 cache store 测试，断言磁盘损坏 JSON 与分层缓存异常 warning。

### GREEN

- 增加 `TaskSummary.chapter_count` / `TaskSummary.word_count` 可选字段。
- 在 `_to_summary()` 中从 `draft_result` / `story_plan` 派生归档指标。
- 调整 `ArchiveListClient` UI 结构和样式。
- 必要时补 cache store 日志实现，但预计已有生产代码满足测试。

### 汇总验证

- `npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts --project=chromium`
- `npm --prefix apps/web test`
- `npm --prefix apps/web run lint`
- `npm --prefix apps/web run build`
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextIntegrationTests::test_result_and_archive_endpoints_expose_json_refs_and_sources apps/agent-runtime/tests/test_context_manager.py -q`
- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_context_manager.py -q`
- `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`
- 若触及共享页面布局或测试稳定性，再跑 `npm --prefix apps/web run test:e2e` 与后端全量 pytest。

## 风险

- 归档列表字段可能缺失：前端指标必须有兜底，后端 contract 测试必须证明真实归档任务会提供指标。
- 长模型 ID 容易造成移动端横向滚动：用 E2E 直接验证视口宽度。
- 后端日志测试不能改变缓存降级语义：异常路径仍必须返回可用 snapshot 或 `None`。
- 本批不能误判 active 全部完成；审核页左右分屏、归档列表之外的阶段 4 项仍保留 active。
