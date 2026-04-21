# 正文分步创建与章节持久化设计

## 背景

当前正文生成链路默认沿 `StoryPlan.chapter_plan` 持续向后推进，章节批次大小主要由系统内部逻辑决定。现状存在四个直接问题：

- 用户无法手工输入目标总章节数。
- 用户无法决定“本次续写几章”。
- 任务恢复依赖运行态与文件产物，缺少章节级结构化状态。
- 大纲审核通过后，系统仍然偏向继续推进，不符合“先审核、再手动分批创作”的工作方式。

现有体系中，正文已经稳定写入 `tasklog/.../artifacts/chapter-xx.md`。这部分不应迁移进数据库。新增能力的重点是补齐“结构化状态层”，让分批续写、任务恢复、章节追踪有明确的单点真相。

## 用户已确认的硬约束

本设计以以下用户确认结论为准：

1. 目标总章节数由用户手工输入，例如 `100`。
2. 前端展示浮动范围，例如 `100 -> 90-110`。
3. 主 agent 只能在该浮动范围内确定最终 `planned_chapter_count`。
4. 大纲审核通过后，不自动开始正文创作。
5. 工作台提供单独的“继续创作”面板。
6. `本次创建章节数` 默认值为 `3`，用户可修改。
7. SQLite 只存结构化状态；正文继续存本地 `md`。
8. 已创作章节必须可恢复、可追踪、可继续往后写。

## 目标

本次设计要解决以下问题：

1. 创建任务时允许用户输入 `target_chapter_count`。
2. 后端基于用户输入生成并持久化 `chapter_count_min` 与 `chapter_count_max`。
3. 大纲阶段输出 `planned_chapter_count`，并强校验其必须落在范围内。
4. 大纲审核通过后进入“可继续创作”，不自动开写正文。
5. 每次只生成一个用户指定大小的批次。
6. 已完成章节写入 SQLite 状态与本地 `md`，支持中断恢复。
7. 恢复时优先使用 SQLite 判断流程位置，再用文件一致性校验正文事实。

## 非目标

- 不把正文全文迁移进 SQLite。
- 不重做整套审核系统。
- 不引入事件溯源式全量重建。
- 不在本次设计中处理“已批准大纲后的全局重分卷/重排章”。

## 术语与最终准绳

### 1. 章节数三元组

#### `target_chapter_count`

- 含义：用户显式输入的目标总章节数。
- 来源：创建任务表单。
- 权限：用户输入后即作为本次任务的主控目标。
- 规则：创建成功后不在正文阶段被隐式修改。

#### `chapter_count_min` / `chapter_count_max`

- 含义：围绕 `target_chapter_count` 生成的允许浮动区间。
- 计算公式：
  - `chapter_count_min = max(1, floor(target_chapter_count * 0.9))`
  - `chapter_count_max = max(chapter_count_min, ceil(target_chapter_count * 1.1))`
- 示例：`100 -> 90-110`
- 规则：创建成功后持久化，不在正文阶段被隐式修改。

#### `planned_chapter_count`

- 含义：主 agent 在大纲阶段给出的最终执行总章节数。
- 来源：`story_plan.planned_chapter_count`
- 强约束：
  - 必须满足 `chapter_count_min <= planned_chapter_count <= chapter_count_max`
  - 必须满足 `len(chapter_plan) == planned_chapter_count`
  - 任一条件不满足，大纲视为无效，进入大纲修订，不得进入正文阶段
- 准绳：正文阶段的最终完成标准以 `planned_chapter_count` 为准，而不是 `target_chapter_count`

### 2. `novel_size` 的优先级

- `novel_size` 继续保留，作为创作规模标签、默认建议和 UI 语义。
- 当用户显式输入 `target_chapter_count` 后，章节总量以 `target_chapter_count` 及其导出的范围为最高优先级。
- 本次设计不要求因为 `novel_size` 与 `target_chapter_count` 的区间语义不一致而阻塞创建；后端只记录该组合，供后续 UI 提示与统计使用。

### 3. 章节推进准绳

- `completed_chapter_count` 只统计“已审核通过”的章节数。
- `next_chapter_number = completed_chapter_count + 1`
- 当 `completed_chapter_count == planned_chapter_count` 时，说明正文已全部完成，应进入全文验证，不再允许继续创作。
- 用户输入的 `requested_chapter_count` 仅表示“本次想创作几章”，实际执行值为：
  - `effective_chapter_count = min(requested_chapter_count, remaining_chapter_count)`
- `effective_chapter_count` 必须持久化到批次表；批次完成、恢复补偿、审核载荷重建一律以 `effective_chapter_count` 为准，不以 `requested_chapter_count` 为准。
- 批次计数强约束：
  - `expected_end_chapter = actual_start_chapter + effective_count - 1`
  - 当 `persisted_count = 0` 时，`actual_end_chapter = NULL`
  - 当 `persisted_count > 0` 时，`actual_end_chapter = actual_start_chapter + persisted_count - 1`
  - 必须满足 `0 <= persisted_count <= effective_count`
  - 恢复时禁止重新按 `requested_chapter_count`、当前剩余章数或最新 `planned_chapter_count` 重新推导 `effective_count`
  - 一旦发现 `effective_count / expected_end_chapter / actual_end_chapter / persisted_count` 不一致，任务直接进入 `waiting_manual_action`

## 用户交互

### 1. 创建任务

创建页新增字段：

- `目标总章节数`
- 只读展示 `允许浮动范围`

提交时后端写入：

- `target_chapter_count`
- `chapter_count_min`
- `chapter_count_max`

### 2. 大纲审核通过

大纲审核通过后：

- 不自动开始正文生成
- 任务进入“可继续创作”
- 工作台显示“继续创作”面板

面板展示：

- `planned_chapter_count`
- `completed_chapter_count`
- `next_chapter_number`
- `remaining_chapter_count`
- 默认 `本次创建章节数 = 3`

### 3. 继续创作

用户点击“继续创作”时必须提交：

- `requested_chapter_count`
- `continue_request_id`

其中：

- `requested_chapter_count` 为本次创作目标章数
- `continue_request_id` 为本次点击生成的幂等键，前端重试必须复用同一个值

### 4. 章节审核通过

章节批次审核通过后：

- 只推进当前批次的章节状态
- 不自动开始下一批
- 返回“可继续创作”
- 等待用户再次触发

## 持久化策略

采用“双轨持久化”：

### 1. SQLite：结构化状态真相

职责：

- 记录章节计划、批次记录、恢复状态、进度统计
- 决定任务当前处于哪个稳定状态
- 决定下一章从哪里开始

### 2. 本地文件：正文内容真相

职责：

- 保存章节正文内容本身
- 作为最终可阅读、可导出的正文产物

### 3. 冲突优先级

当 SQLite 与文件系统不一致时，按以下规则处理：

1. 流程位置以 SQLite 为主。
2. 正文内容字节事实以本地 `md` 文件为主，但前提是文件存在且校验值与数据库一致。
3. 若数据库记录显示章节已落盘，但文件缺失或校验不一致，则该章节不得视为有效章节，任务进入人工处理或恢复补偿分支。
4. 若文件存在但数据库未更新，且该文件属于当前活动批次的预期章节范围，则允许恢复流程回填数据库元数据。
5. 若章节已处于 `approved` 或 `rejected`，后续发现文件损坏时，不自动改写审核结论，但必须立即阻塞后续创作、验证、导出，并切换到 `waiting_manual_action`。
6. 对于审核后的产物漂移，业务状态保留，文件一致性状态单独记录；恢复路径是“先修复产物一致性，再恢复业务流程”，而不是静默覆盖业务状态。

## 双写顺序、幂等与补偿

这是本设计的核心执行约束。

### 1. 批次幂等键

- `continue_request_id` 是“继续创作”接口的幂等键。
- 唯一性约束：`(task_id, continue_request_id)` 唯一。
- 重复提交规则：
  - 若同一个 `continue_request_id` 已存在，则返回该批次当前状态，不新建批次。
  - 若任务已有未结束批次，而用户提交不同的 `continue_request_id`，后端拒绝请求并返回冲突。

### 1.1 原子认领规则

- 批次创建与执行权认领必须是原子操作，不能只依赖唯一索引。
- 后端必须在单个数据库事务内完成以下 compare-and-set：
  - `novel_project.status: ready_for_batch -> batch_generating`
  - 写入 `active_batch_no`
  - 写入 `active_continue_request_id`
  - 将目标批次状态从 `created` 或可恢复态切到 `drafting`
- 任一 compare-and-set 失败，说明已有其他执行者持有该批次或项目执行权：
  - 若持有者的 `continue_request_id` 与当前请求相同，则返回该批次快照，不重复启动写入
  - 若不同，则直接拒绝，避免并发双写
- 恢复流程与实时请求共用同一套认领规则，不允许绕过 compare-and-set 直接接管活动批次
- 批次执行者必须持有 `claim_token` 租约：
  - 批次进入 `drafting` 时写入新的 `claim_token`
  - 每成功持久化一章后刷新 `claimed_at`
  - 只有 `claim_token` 匹配的执行者才允许回写章节状态与批次进度
  - 租约是否过期由 `claimed_at + lease_timeout_seconds` 判断，`lease_timeout_seconds` 作为可配置常量存在
- 接管规则：
  - 只有当活动批次 `claim_token` 缺失，或租约已超时，恢复流程才允许原子替换 `claim_token` 并接管
  - 实时用户请求不能抢占正在持有有效租约的活动批次
  - 若租约仍有效，则返回当前批次状态；若租约失效，则只能恢复该批次，不能绕过旧批次直接新开批次

### 2. 双写顺序

单个批次的推荐写入顺序固定为：

1. 在 SQLite 中创建或获取批次记录，状态置为 `drafting`
2. 写入批次元数据：
   - `requested_count`
   - `effective_count`
   - `actual_start_chapter`
   - `expected_end_chapter`
   - `persisted_count = 0`
3. 对每一章循环执行：
   - 先将章节写入临时文件 `chapter-xx.md.tmp`
   - 再原子替换为正式文件 `chapter-xx.md`
   - 计算 `content_hash`、`file_size`
   - 回写章节表，将该章置为 `drafted`
   - 批次表 `persisted_count + 1`
4. 当本批所有章节都成功写库后：
   - 批次状态置为 `waiting_review`
   - 项目状态置为 `waiting_chapter_review`

### 3. 为什么采用“先建批次，再文件，再回写章节状态”

- 需要先把批次边界写入数据库，恢复时才知道本批原本计划写哪些章。
- 章节正文必须先落到文件，再回写数据库为 `drafted`，否则会出现数据库显示已完成但正文文件不存在的假完成状态。
- 章节级别使用原子重命名，减少半写入文件被误判为有效正文。

### 4. 补偿规则

#### 文件写入失败，数据库尚未更新章节状态

- 保持该章为 `planned`
- 保持批次为 `drafting`
- 记录错误信息
- 恢复时从该章继续

#### 文件已写成功，但章节状态回写数据库失败

- 批次保持 `drafting`
- 恢复时扫描该批次预期范围
- 若发现正式文件存在，则补写该章的 `md_ref`、`content_hash`、`file_size`，再继续后续章节

#### 全部章节文件已存在，批次最终状态未切到 `waiting_review`

- 恢复时若发现 `persisted_count == effective_count` 且文件校验全部通过，则自动将批次提升到 `waiting_review`

#### 数据库记录为 `drafted`，但文件丢失或校验不一致

- 不自动覆盖原文件
- 将该章标记为 `artifact_state = file_missing` 或 `checksum_mismatch`
- 任务进入 `waiting_manual_action`

#### 章节已 `approved` 或 `rejected`，但后续发现文件损坏

- 不回退审核结论
- 将章节与项目标记为产物漂移
- 阻塞以下动作：
  - 下一批继续创作
  - 全文验证
  - 结果装配与导出
- 恢复入口统一转到 `waiting_manual_action`

## 数据模型

### 1. `novel_project`

任务级小说状态表，用于单点真相与恢复入口。

建议字段：

- `task_id`
- `novel_title`
- `creative_mode`
- `novel_size`
- `target_chapter_count`
- `chapter_count_min`
- `chapter_count_max`
- `planned_chapter_count`
- `chapter_word_min`
- `chapter_word_max`
- `default_batch_size`
- `completed_chapter_count`
- `next_chapter_number`
- `status`
- `active_batch_no`
- `active_continue_request_id`
- `blocked_from_status`
- `last_checkpoint_stage`
- `last_consistency_state`
- `created_at`
- `updated_at`

硬约束：

- `next_chapter_number = completed_chapter_count + 1`
- `completed_chapter_count <= planned_chapter_count`
- `status` 只使用稳定态，不记录半章级瞬时噪音

### 2. `novel_outline_chapter`

章节计划与章节推进表。

建议字段：

- `task_id`
- `chapter_number`
- `title`
- `goal`
- `status`
- `batch_no`
- `summary`
- `md_ref`
- `json_ref`
- `content_hash`
- `file_size`
- `artifact_state`
- `file_checked_at`
- `updated_at`

状态值：

- `planned`
- `drafted`
- `approved`
- `rejected`

`artifact_state` 建议值：

- `pending`
- `present`
- `file_missing`
- `checksum_mismatch`

### 3. `novel_generation_batch`

一次“继续创作”操作对应一条批次记录。

建议字段：

- `task_id`
- `batch_no`
- `continue_request_id`
- `requested_count`
- `effective_count`
- `actual_start_chapter`
- `expected_end_chapter`
- `actual_end_chapter`
- `persisted_count`
- `status`
- `attempt_no`
- `claim_token`
- `claimed_at`
- `error_code`
- `error_message`
- `created_at`
- `updated_at`
- `finished_at`

状态值：

- `created`
- `drafting`
- `waiting_review`
- `approved`
- `rejected`
- `failed`

## 索引设计

至少增加以下索引：

- `novel_project(task_id)` 唯一索引
- `novel_project(status, updated_at)` 组合索引
- `novel_outline_chapter(task_id, chapter_number)` 唯一索引
- `novel_outline_chapter(task_id, status)` 普通索引
- `novel_outline_chapter(task_id, artifact_state)` 普通索引
- `novel_generation_batch(task_id, batch_no)` 唯一索引
- `novel_generation_batch(task_id, continue_request_id)` 唯一索引
- `novel_generation_batch(task_id, status)` 普通索引
- `novel_generation_batch(task_id, created_at desc)` 普通索引

## 稳定状态机

这里定义 `novel_project.status` 的稳定状态，供前端、恢复逻辑和接口校验共用。

### 1. `waiting_outline_review`

- 大纲已生成，等待用户审核
- 不允许继续创作

### 2. `ready_for_batch`

- 大纲已审核通过
- 当前没有活动批次
- 允许用户点击“继续创作”

### 3. `batch_generating`

- 已创建活动批次
- 批次正在写文件/回写章节状态
- 不允许再开新批次

### 4. `waiting_chapter_review`

- 当前批次所有目标章节已稳定落盘
- 等待用户审核该批次

### 5. `waiting_verification_review`

- 全部章节均已审核通过
- 等待全文验证

### 6. `completed`

- 全文验证完成，产物装配完成

### 7. `failed`

- 批次或任务执行失败，且不满足自动恢复条件

### 8. `waiting_manual_action`

- 检测到文件缺失、校验不一致、关键状态缺失等问题
- 不进行自动推进，等待人工处理

## 工作流调整

### 1. 创建阶段

- 前端提交 `target_chapter_count`
- 后端同步生成 `chapter_count_min` / `chapter_count_max`
- 初始化 `novel_project`

### 2. 大纲阶段

- 主 agent 输出 `planned_chapter_count + chapter_plan`
- 后端验证章节数三元组关系
- 审核通过后：
  - 把 `chapter_plan` 批量写入 `novel_outline_chapter`
  - `novel_project.status = ready_for_batch`

### 3. 正文批次阶段

用户触发“继续创作”后：

1. 校验项目状态必须为 `ready_for_batch`
2. 原子认领项目与批次执行权
3. 创建或获取幂等批次
4. 计算并持久化 `effective_chapter_count`
5. 按 `next_chapter_number` 起步生成对应范围的章节
6. 每成功持久化一章，就更新一章与批次进度
7. 全批完成后进入 `waiting_chapter_review`

### 4. 章节审核通过后的推进

章节批次审核通过时：

- 将本批章节状态从 `drafted` 改为 `approved`
- `completed_chapter_count += 本批通过章节数`
- `next_chapter_number = completed_chapter_count + 1`
- 若 `completed_chapter_count < planned_chapter_count`
  - `novel_project.status = ready_for_batch`
- 若 `completed_chapter_count == planned_chapter_count`
  - `novel_project.status = waiting_verification_review`

### 5. 章节审核拒绝后的推进

- 当前批次状态标记为 `rejected`
- 已落盘章节保留，不自动删除
- 项目状态回到 `ready_for_batch`
- 后续由用户决定是否重新发起下一次批次创作或人工修正

## 恢复判定树

恢复逻辑必须基于稳定状态，而不是仅依赖运行时内存。

### 1. 入口检查

恢复时先读取：

- `novel_project`
- 最新未终态 `novel_generation_batch`
- 当前任务的 `novel_outline_chapter`

恢复前先执行一致性前置检查：

- 若任一 `approved` 或 `rejected` 章节的 `artifact_state != present`
  - 直接切换到 `waiting_manual_action`
  - 记录 `blocked_from_status`
  - 阻塞继续创作、验证、导出
- 只有历史已审核章节的文件一致性通过后，才允许进入后续恢复判定

### 2. 判定顺序

#### 情况 A：`status = waiting_outline_review`

- 直接恢复到大纲审核页

#### 情况 B：`status = ready_for_batch`

- 若不存在活动批次，直接恢复到“继续创作”面板
- 若存在非终态批次，说明状态脏，进入批次核查

#### 情况 C：`status = batch_generating`

读取活动批次范围，按以下顺序检查：

1. 若 `persisted_count = 0` 且无正式文件
   - 可安全从 `actual_start_chapter` 重启该批次
2. 若 `0 < persisted_count < effective_count`
   - 校验已落盘章节文件是否存在且校验值匹配
   - 若一致，则从下一缺失章节继续该批次
   - 若不一致，则转 `waiting_manual_action`
3. 若 `persisted_count = effective_count`
   - 校验全部文件
   - 若一致，则提升到 `waiting_chapter_review`
   - 若不一致，则转 `waiting_manual_action`

#### 情况 D：`status = waiting_chapter_review`

- 从章节表与文件系统重建批次审核载荷
- 若本批章节文件齐全且一致，则恢复到章节审核页
- 否则转 `waiting_manual_action`

#### 情况 E：`status = waiting_verification_review`

- 若 `completed_chapter_count == planned_chapter_count`
  - 直接恢复到全文验证审核
- 否则说明状态脏，转人工处理

#### 情况 F：`status = completed`

- 直接展示结果页

#### 情况 G：`status = waiting_manual_action` 或 `failed`

- 不自动续跑
- 展示错误摘要与缺失项

#### 情况 H：人工修复后的回迁

- 当任务处于 `waiting_manual_action` 时，允许执行“产物一致性修复/重扫”动作
- 修复动作只做两件事：
  - 重扫受影响章节文件
  - 重建 `content_hash` / `file_size` / `artifact_state`
- 回迁条件：
  - 若所有受影响章节都恢复为 `artifact_state = present`
  - 且 `effective_count / expected_end_chapter / actual_end_chapter / persisted_count` 一致
  - 则按 `blocked_from_status` 回迁
- 回迁目标：
  - `blocked_from_status = ready_for_batch`，回到继续创作面板
  - `blocked_from_status = waiting_chapter_review`，回到当前批次审核
  - `blocked_from_status = waiting_verification_review`，回到全文验证
  - `blocked_from_status = completed`，先重建结果装配产物，再回到结果页

## 最小改造落点

### 后端

- `apps/agent-runtime/app/domain/models.py`
  - 增加目标总章节数、浮动范围、批次请求字段
- `apps/agent-runtime/app/storage/db_models.py`
  - 新增 `novel_project` / `novel_outline_chapter` / `novel_generation_batch`
- `apps/agent-runtime/app/storage/db_repository.py`
  - 增加项目、章节、批次的 upsert 与恢复查询
- `apps/agent-runtime/app/storage/task_store.py`
  - 保留正文文件落盘，增加文件校验信息输出
- `apps/agent-runtime/app/application/task_service.py`
  - 增加“继续创作”接口、幂等处理、恢复判断
- `apps/agent-runtime/app/graph/main_graph.py`
  - 改为按批次推进，不再默认全量推进
- `apps/agent-runtime/app/api/routes.py`
  - 新增继续创作接口与批次查询接口

### 前端

- `apps/web/src/features/task-create/create-task-client.tsx`
  - 增加目标总章节数输入与浮动范围展示
- `apps/web/src/features/task-run/task-run-client.tsx`
  - 增加“继续创作”面板与本次章节数输入
- `apps/web/src/features/task-review/task-review-client.tsx`
  - 审核通过后不自动进入下一批
- `apps/web/src/lib/types.ts`
  - 增加章节数与批次状态字段

## 验收标准

以下场景全部成立，才算设计可进入实现：

1. 用户输入 `100` 章时，后端稳定产出 `90-110` 范围。
2. 若大纲输出 `planned_chapter_count = 120`，系统必须拒绝并要求修订。
3. 大纲审核通过后，任务只能进入 `ready_for_batch`，不能直接开始正文创作。
4. 同一个 `continue_request_id` 重复请求不会重复创建批次。
5. 不同 `continue_request_id` 在已有活动批次时会被拒绝。
6. 批次创作过程中若已成功写出前 2 章、第 3 章失败，恢复后能从第 3 章继续，而不是重写前 2 章。
7. 若数据库显示章节已 `drafted`，但 `chapter-xx.md` 缺失，任务必须转入人工处理，不能静默跳过。
8. 当全部章节审核通过后，任务进入 `waiting_verification_review`，而不是继续开放“继续创作”。

## 推荐实施顺序

1. 补齐数据模型与索引
2. 接入创建页章节总数输入与后端校验
3. 接入大纲审核通过后的 `ready_for_batch`
4. 实现继续创作接口与批次幂等
5. 实现章节批次生成与双写闭环
6. 实现批次恢复判定树
7. 补前后端交互与全链路测试
