# ProjectShell/StageNav 与 MVP 第三批清理 Design

## 背景

当前 active 任务有两条：UI/UX 后续阶段，以及 MVP 审查后续日志覆盖与死代码清理。上一批已完成首页作品库切片和第二批低风险清理，但仍留下阶段 3/4 的项目级页面结构、以及模型兼容性相关异常日志覆盖缺口。

本批只做可验证的小切片，不迁移路由，不重构工作台大组件，不改变模型兼容性验证的对外语义。

## 目标

1. 抽出统一的 `StageNav`，先替换审核页和结果页重复阶段条。
2. 抽出轻量 `ProjectShell`，先统一审核页和结果页的面包屑、标题、元信息与动作区。
3. 修复模型兼容性缓存损坏导致模型目录刷新时重复 warning 的日志放大问题。
4. 为模型兼容性缓存失效、网关可见性解析、动态协议覆盖解析三处静默降级补 warning。
5. 修复首页项目卡片底部长任务 ID 可能造成移动端横向溢出的风险。

## 非目标

- 不接入 `/p/[projectId]` 工作台；该页面体量大，等 shell/nav 稳定后再分批处理。
- 不改审核业务状态机、结果接口或归档接口。
- 不删除运行时仍可能被外部使用的 API 契约。
- 不在本批抽离归档 `ChapterReader`；该项留给后续阶段 3 切片。

## UI 设计

### StageNav

`StageNav` 是跨页面阶段导航组件，放在 `apps/web/src/components/stage-nav.tsx`，输入为阶段数组和当前阶段索引。它渲染为一个可横向滚动的紧凑步骤条，带 `data-testid="stage-nav"` 和 `aria-label="任务阶段导航"`，移动端不撑宽页面。容器必须设置 `minWidth: 0` 与 `overflowX: "auto"`，阶段项使用稳定最小宽度和 `flexShrink: 0`，避免制造页面级横向滚动。

审核页继续根据 `review_type` 和 `outline_batch.phase` 选择原有阶段序列，只把渲染从局部 `StepIndicator` 换成共享 `StageNav`。结果页固定使用“创建 / 运行 / 审核 / 结果”，当前阶段为“结果”。

### ProjectShell

`ProjectShell` 负责项目页面的外壳，放在 `apps/web/src/components/project-shell.tsx`，不是全站布局。它接收：

- `breadcrumbs`：首页、工作台、当前页。
- `title`：页面主标题。
- `metaItems`：任务标题、状态、模型等 Chip/短文本。
- `actions`：仅承载当前页面顶部已有动作，例如“返回工作台”。
- `stageNav`：可选阶段条插槽。

审核页和结果页先接入该壳。结果页的复制全文、导出 MD 继续留在正文卡片内，不迁移到页面头部，避免改变用户工作流。归档详情页暂不接入，避免把阅读器抽离和 shell 引入混在同一批。

## 后端设计

### 模型兼容性缓存读取

`ModelCompatibilityService` 当前每次 `get_report()` 都会读取 `model_compatibility.json`。如果文件损坏，目录聚合会对多个模型重复调用 `get_report()`，导致一次刷新产生多条重复 warning。

本批在服务实例内缓存一次读取结果，并记录文件 `mtime_ns/size` 指纹。文件未变化时复用缓存；文件变化或保存报告后刷新缓存。损坏文件仍返回空 store，且同一个损坏指纹只记录一次 warning。

### 静默降级日志

三处保持原返回语义，只补 warning：

- `_invalidate_model_catalog_cache()`：invalidator 抛错时记录 warning 后继续。
- `_gateway_visible()`：resolver 抛错时记录 warning，继续返回 `False`。
- `OpenAICompatibleGatewayClient._resolve_protocol()`：动态覆盖 resolver 抛错时记录 warning，继续使用静态覆盖和默认协议。

## 首页长 ID 风险

首页项目卡片底部 `ID {task.task_id}` 增加 `overflowWrap: "anywhere"` 与 `minWidth: 0`，并扩展现有移动端 E2E fixture 覆盖长不可断任务 ID。

## 测试策略

- 后端先写失败测试：
  - 损坏 `model_compatibility.json` 在多模型目录聚合中只产生一次 warning。
  - 损坏文件同一指纹只 warning 一次，内容变化或修复后重新读取。
  - 外部修改 `model_compatibility.json` 后 `get_report()` 能读到新内容。
  - `save_report()` 和 `clear_report()` 后缓存立即同步。
  - invalidator 抛错时记录 warning，`save_report()` 不抛出。
  - gateway resolver 抛错时 `_gateway_visible()` 返回 `False` 并记录 warning。
  - protocol overrides resolver 抛错时协议回退不变并记录 warning。
- 前端先写失败测试：
  - `StageNav` helper 单测覆盖当前阶段和完成态计算。
  - 审核页大纲总纲、章节审核、验证审核 E2E 断言统一 `project-shell` 与 `stage-nav` 存在，并检查当前阶段。
  - 结果页 E2E 断言统一 `project-shell` 与 `stage-nav` 存在，并检查当前阶段为“结果”。
  - 首页移动端 E2E 使用长不可断任务 ID，断言 document 与项目卡片均无横向溢出。
- 验证命令：
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_model_compatibility.py apps/agent-runtime/tests/test_model_catalog.py apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py -q`
  - `uv run --project apps/agent-runtime ruff check apps/agent-runtime/`
  - `npm --prefix apps/web test`
  - `npm --prefix apps/web run lint`
  - `npm --prefix apps/web run build`
  - `npm --prefix apps/web run test:e2e -- review-result-archive.spec.ts home-create.spec.ts --project=chromium`

## 风险

- 审核页和结果页组件较大，本批只替换外壳和阶段条，不移动业务表单与加载逻辑。
- 后端缓存必须在 `save_report()`、`clear_report()` 后可见最新数据，否则会影响模型验证 UI。测试会覆盖保存后目录缓存失效。
- E2E 选择器必须使用稳定 test id 或可访问名称，避免绑定 MUI 内部结构。

## 执行门禁与收口

- 本批对应两个 active worklog，实施过程中必须同步更新：
  - `worklog/active/UI优化/20260629-02-UIUX体验重塑后续阶段.md`
  - `worklog/active/项目审查/20260629-01-MVP审查后续日志覆盖与死代码清理.md`
- 用户已确认继续推进，因此可以执行本计划；后续若扩大范围，需要重新记录讨论结论。
- 完成后若阶段 3/4 或 MVP 清理仍有剩余，active 文档不得归档。
- 若用户明确要求收口提交，必须先归档已完成 active 项并更新 `worklog/index.md` / `worklog/history.md`，再提交。
- 提交前必须核对 `git status --short`，确认不包含任何 `.superpowers/` 路径。
