# 问题标题

缓存命中率与 Provider Prompt Cache 优化

## 用户原始诉求

在完成当前内容归档提交后，继续推进缓存问题。此前已确认本地最终响应缓存仍因逐章动态上下文导致命中率不高，需要进一步解决缓存命中率与请求耗时问题。

## 当前状态

- 状态：进入讨论与方案设计阶段，尚未修改代码。
- 约束：不能粗暴放宽最终响应缓存 key，避免章节正文、审核反馈或上一章上下文错误复用。
- 既有基础：已在上一批次增加 prompt 稳定前缀 hash、动态尾部 hash、每段 message hash 与 JSON 解析耗时诊断。

## 初步方向

- 方向一：Provider Prompt Cache 接入。
  - 目标：对系统提示、风格样例、世界观、大纲、长期规则等稳定前缀增加供应商级 prompt cache 标记。
  - 风险：需要确认当前 K2.6/网关协议是否透传 Anthropic/OpenAI 兼容 cache 控制字段。
- 方向二：Prompt 结构稳定化。
  - 目标：把稳定内容前置并保持顺序稳定，将章节号、上一章全文、已完成摘要等动态内容放在尾部。
  - 风险：需要保证 story_engine 各阶段输出语义不变，不能破坏章节连续性。
- 方向三：可复用中间结果缓存。
  - 目标：缓存大纲摘要、风格约束、RAG 选材结果、章节历史压缩包等中间产物，而不是缓存最终章节正文。
  - 风险：需要定义失效条件，避免源素材或大纲变更后复用旧上下文。

## 执行进展

- 已接入 Anthropic Messages API prompt cache 结构：
  - `system` 可在达到最小长度时转换为带 `cache_control` 的 text block。
  - 用户消息可按章节动态 marker 拆分为“稳定前缀块 + 动态尾部块”，稳定前缀块标记 `cache_control`。
  - `OpenAIAdapter` 不注入未知缓存字段，避免污染 OpenAI 兼容 payload。
- 已新增配置：
  - `PROVIDER_PROMPT_CACHE`，默认开启。
  - `PROVIDER_PROMPT_CACHE_MIN_CHARS`，默认 1024。
  - `PROVIDER_PROMPT_CACHE_TTL`，默认空，不强制发送 ttl。
- 已调整章节生成 prompt 顺序：
  - 作品标题、梗概、总章节规划、风格约束、上下文记忆、参考摘要前置为稳定前缀。
  - 当前章节号、章节目标、已完成摘要、上一章全文、历史草稿保留在动态尾部。
- 已更新 K2.6 模型能力画像：`provider_prompt_cache=anthropic_cache_control`。
- 验证：
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_protocol_adapter.py apps/agent-runtime/tests/test_gateway_max_tokens_injection.py -q`：31 passed。
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py apps/agent-runtime/tests/test_model_catalog.py -q`：33 passed。
  - `uv run --project apps/agent-runtime ruff check ...`：All checks passed。
  - 本地 payload 探测确认章节 prompt 经 AnthropicAdapter 后变为两个 content block，稳定前缀带 `cache_control`，动态尾部从 `当前章节序号` 开始。
  - 真实/半真实 K2.6 连续请求探测：
    - 配置：`base_host=api.udcode.cn`，`model=K2.6`，`adapter=AnthropicAdapter`，`endpoint=/messages`。
    - payload：`provider_prompt_cache=True`，`prompt_cache_min_chars=1024`，用户消息拆为 2 个 content block，第一块带 `cache_control`，稳定块约 4125 字符。
    - 第 1 次请求：`status=200`，耗时约 `2489.14ms`，`input_tokens=2856`，`cached_tokens=0`，`cache_read_input_tokens=0`。
    - 第 2 次相同请求：`status=200`，耗时约 `1156.87ms`，`input_tokens=0`，`cached_tokens=2856`，`cache_read_input_tokens=2856`。
    - 结论：当前 K2.6 网关会透传 Anthropic prompt cache 结构，且第二次相同稳定前缀请求实际命中 Provider Prompt Cache；本次延迟下降约 53.5%。

## 下一步

- 需要把 usage 中的 `cache_read_input_tokens`、`cached_tokens` 等字段接入事件流或诊断面板，方便在真实章节任务中持续观察命中情况。
- 可继续推进中间结果缓存：RAG 选材结果、风格约束摘要、历史章节压缩包，避免最终正文错误复用。

## 新增讨论：缓存掉线与章节批量并行

- 用户反馈：
  - 仍会出现 Provider Prompt Cache 掉缓存。
  - 整体执行流程耗时长。
  - 当设置一次性创建 3 章时，例如 1-3 章，用户认为可以按大纲和章节规划并行生成。
  - 希望并行线程数写入配置，默认 4，最大 6。
- 初步判断：
  - 缓存掉线需要继续稳定缓存断点，并把 usage 字段写入事件流，明确是 TTL、断点变化、长度不足、模型/协议切换还是动态内容进入稳定块导致。
  - 章节并行可以做，但不能把当前依赖“上一章全文”和“已完成摘要”的连续性逻辑直接并行化；更稳妥的是并行生成章节草稿，再按章节顺序做连续性校验、补缝和最终落盘。
  - 线程数应做配置化，并加硬上限，避免再次出现 CPU 或上游请求并发过高导致系统卡顿。

## 执行进展：缓存观测与章节并行草稿

- 已新增流式 usage 进度事件：
  - 当网关返回 `cache_read_input_tokens`、`cached_tokens`、`cache_creation_input_tokens` 等 usage 字段时，后端会产生 `model.usage` 事件并写入任务事件流。
  - 目标是在真实章节任务中能持续判断掉缓存原因，而不是只靠一次性探测脚本。
- 已新增章节并行草稿配置：
  - `CHAPTER_PARALLEL_DRAFT_ENABLED=true`
  - `CHAPTER_PARALLEL_MAX_WORKERS=4`
  - `CHAPTER_PARALLEL_MIN_BATCH_SIZE=3`
  - 代码内硬限制 worker 最大为 6。
- 并行策略：
  - 3 章及以上批次启用并行草稿。
  - 2 章以内继续保持原顺序生成路径，避免破坏默认章节承接。
  - 风格仿写模式默认保持顺序路径，降低语气连续性回归风险。
  - 并行批次完成后按章节号排序返回，保证落盘顺序稳定。
- 已补充 `.env.example`，显式写出 prompt cache 与章节并行配置。
- 验证：
  - 新增测试先红后绿，覆盖 `model.usage` 事件、3 章批次并行、worker 最大 6 限幅。
  - `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py apps/agent-runtime/tests/test_protocol_adapter.py apps/agent-runtime/tests/test_gateway_max_tokens_injection.py apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py apps/agent-runtime/tests/test_model_catalog.py apps/agent-runtime/tests/test_batched_chapter_generation.py apps/agent-runtime/tests/test_recovery_chapter_progress.py apps/agent-runtime/tests/test_task_service_review_resume.py -q`：110 passed，1 skipped。
  - `uv run --project apps/agent-runtime ruff check ...`：All checks passed。
  - `git diff --check`：通过。

## 提效测试记录

- 本地假网关隔离基准：
  - 场景：3 章批次，每章固定模拟 350ms 网关延迟。
  - 串行：`1061.09ms`，`calls=3`，`max_active=1`。
  - 并行：`356.78ms`，`calls=3`，`max_active=3`。
  - 结果：提速约 `2.97x`，耗时下降约 `66.38%`。
- K2.6 短请求真实/半真实基准：
  - 配置：`base_host=api.udcode.cn`，`model=K2.6`，`adapter=AnthropicAdapter`，`endpoint=/messages`。
  - payload：用户消息拆为 2 个 content block，稳定块约 `3895` 字符，第一块带 `cache_control`。
  - 预热请求：`1957.75ms`，`input_tokens=2700`，`cached_tokens=0`。
  - 串行 3 请求总耗时：`4322.37ms`。
    - 第 1 请求命中：`cached_tokens=2560`，`elapsed_ms=1091.32`。
    - 第 2 请求掉缓存：`cached_tokens=0`，`elapsed_ms=1735.08`。
    - 第 3 请求掉缓存：`cached_tokens=0`，`elapsed_ms=1495.57`。
  - 并行 3 请求总耗时：`1670.48ms`。
    - 第 4 请求命中：`cached_tokens=2560`，`elapsed_ms=1156.87`。
    - 第 5 请求命中：`cached_tokens=2560`，`elapsed_ms=1224.08`。
    - 第 6 请求掉缓存：`cached_tokens=0`，`elapsed_ms=1665.85`。
  - 结果：短请求真实/半真实提速约 `2.59x`，耗时下降约 `61.35%`。
  - 观察：同一稳定前缀下仍存在 Provider Prompt Cache 偶发不命中，说明掉缓存不完全由本地 prompt 结构导致，也可能与上游缓存路由、TTL、并发时机或缓存创建传播有关。
