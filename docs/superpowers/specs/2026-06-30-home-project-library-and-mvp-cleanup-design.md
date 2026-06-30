# 首页作品库 2B 与 MVP 第二批清理设计

## 背景

当前 UI/UX 重塑阶段 2A 已完成 `/new` 与 `/p/[projectId]` 入口迁移，但首页仍以“任务列表”呈现。MVP 审查后续任务已完成第一批低风险清理，仍有可独立处理的死代码与异常日志覆盖点。

本轮目标是在不扩大路由迁移范围的前提下完成两个小切片：

- 首页从紧凑任务列表升级为更可扫描的作品库项目卡片。
- MVP 审查第二批只处理已复核的低风险清理与日志覆盖。

## 已确认范围

### 首页作品库 2B

- 保留现有 Dashboard API、分组 Tab、失败任务重试、删除任务、默认模型切换与侧栏统计。
- 首页主标题从“任务列表”语义调整为“作品库/项目库”语义。
- 单个项目项改为卡片化信息层级：标题、摘要、状态、阶段、类型、更新时间、主操作入口。
- 运行中/待处理/失败/完成四个分组仍使用现有分页逻辑。
- 移动端以单列卡片呈现，不允许出现横向溢出。

### MVP 第二批

- 删除未使用的 `apps/web/src/lib/fonts.ts`，保留 `globals.css` 中现有系统字体 CSS 变量。
- 删除未被调用的 `save_runtime_settings()`，保留现有读写内部函数与协议覆盖 API。
- `MODEL_PROTOCOL_OVERRIDES` 环境变量解析失败时记录 warning，外部返回语义仍为 `{}`。
- 模型兼容性缓存 JSON 损坏时记录 warning，外部仍返回 `unverified` 降级结果。

## 非目标

- 不迁移 `reviewHref`、`resultHref`、`archiveDetailHref` 到新路由。
- 不拆分 `TaskRunClient`、`TaskReviewClient` 等大组件。
- 不重做暗黑模式全站精调。
- 不修改 Dashboard API 契约。
- 不引入新 UI 框架或新状态管理。

## UI 设计

首页主内容仍采用左侧项目库、右侧运营状态的工作台布局。项目卡片使用 MUI `Card`、`Chip`、`Button`、`Grid` 与 `sx` 响应式样式，控制圆角不超过现有卡片风格，避免营销式 hero 和装饰性背景。

项目卡片信息层级：

- 第一行：项目标题、状态 Chip、主操作按钮。
- 第二行：摘要，最多两行。
- 第三行：阶段、任务类型、更新时间。
- 失败状态显示“重新创建”和“删除”；可删除状态保留删除按钮。

移动端按钮允许换行，卡片内容使用 `minWidth: 0`、`overflowWrap` 和稳定间距，保证 390px 宽度无横向滚动。

## 数据流

不新增后端数据。`TaskCardSummary` 现有字段已满足展示需要：

- `title`
- `summary`
- `status`
- `current_stage`
- `creative_mode`
- `novel_size`
- `mode`
- `updated_at`
- `storage_state`

`resolveTaskHref()` 保持现状，用于根据任务状态进入工作台、审核、结果或归档详情。

## 错误处理

首页删除、模型切换、模型验证跳转沿用现有错误处理。MVP 第二批只补充 warning 日志，不改变异常降级语义。

## 测试策略

- 先补 Playwright E2E，断言首页展示作品库语义、项目卡片标题/摘要/状态/阶段/类型/主入口。
- 补移动端 E2E，viewport 390x844 下断言 `documentElement.scrollWidth <= clientWidth`。
- 保留已有失败任务重试、删除任务、默认模型切换测试。
- 后端日志覆盖先写失败测试，再补 warning。
- 删除死代码先写导出/源码级测试或扩展现有行为测试，再改实现。
