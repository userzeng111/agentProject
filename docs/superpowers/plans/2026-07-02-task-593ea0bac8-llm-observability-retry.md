# task_593ea0bac8 LLM 观测与空响应重试 Implementation Plan

> **给后续 agentic worker:** REQUIRED SUB-SKILL: 使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实施。步骤使用 checkbox（`- [ ]`）跟踪。

**Goal:** 修复 task_593ea0bac8 暴露的结构化 JSON 空响应失败，并把调试面板中的 LLM 缓存与 Trace 观测口径拆清楚。

**Architecture:** 以任务事件流为事实来源，后端增加明确的缓存口径与空响应诊断，前端只展示标准化后的诊断字段。结构化 JSON 生成遇到 `finish_reason=length/max_tokens` 且正文为空时，不直接进入通用 repair，而是先执行一次更短、更硬的 JSON-only retry。

**Tech Stack:** FastAPI/Pydantic 后端、LangGraph 工作流、`StoryEngine` LLM 调用封装、Next.js 14 前端、Python `pytest`、Node `tsx --test`。

---

## 范围

本计划对应用户选择的 B 方案：观测 + 当前失败链路修复。

纳入本批次：
- `chapter-pair-revision` 空正文且 `length/max_tokens` 的专用重试。
- `LLM 摘要` 调试面板缓存口径拆分。
- 结构化日志与事件诊断增强，便于查找类似失败。
- 保持既有 `cache_hit_count` 兼容，新增更明确字段。

不纳入本批次：
- 模型上下文窗口“接口值优先”的完整实现。该部分属于 C 方案，已有调查结论，但不在本计划中改模型目录合并逻辑。
- 大范围重构 Agent Trace 数据模型。
- 修改业务创作语义、章节审核策略或自动审核评分逻辑。

## 项目门禁

- 当前计划只允许在用户明确说“执行/继续/同意执行”后进入代码修改。
- 实施前检查是否存在 `src/Cargo.toml`。当前调查未发现 Cargo workspace；若实施时仍不存在，记录“无可 bump 的 Cargo 版本文件”。
- 提交前必须等用户明确同意收口，并按项目规则先归档 `worklog/active` 到 `worklog/archive`，再执行中文提交。
- 不在中间任务随意提交；最后收口统一提交。

## 文件结构

后端：
- Modify: `apps/agent-runtime/app/llm/story_engine.py`
  - 增加章节修订空响应 retry prompt。
  - 允许“同预算但提示词改变”的空正文截断重试。
  - 在 retry 日志中记录 `stage`、`exchange_label`、`finish_reason`、`max_tokens`、`retry_max_tokens`、`content_chars`、`reasoning_chars`，不记录正文。
- Modify: `apps/agent-runtime/app/application/task_service/queries.py`
  - `llm_report` 新增 `runtime_response_cache_hit_count`、`provider_prompt_cache_hit_count`。
  - `cache_hit_count` 保持为运行时响应缓存命中数，避免破坏旧字段。
- Modify: `apps/agent-runtime/tests/test_story_engine_context.py`
  - 增加 `chapter-pair-revision` reasoning-only length 回归测试。
- Modify: `apps/agent-runtime/tests/test_api_context.py`
  - 增加 `llm_report` 新缓存口径字段测试。

前端：
- Modify: `apps/web/src/lib/types.ts`
  - 给 `LlmReport` 增加新字段。
- Modify: `apps/web/src/features/task-run/debug-diagnostics.mjs`
  - 从后端 report 或事件兜底派生响应缓存命中、供应商缓存命中。
- Modify: `apps/web/src/features/task-run/debug-panel.tsx`
  - 把“缓存命中”改成“响应缓存命中”，新增“供应商缓存命中”和“缓存 tokens”。
- Modify: `apps/web/src/features/task-run/debug-diagnostics.test.mjs`
  - 增加新展示口径测试。

文档与记录：
- Modify: `worklog/active/LLM调用/20260702-01-task-593ea0bac8-trace-summary-cache-context.md`
  - 记录实施进度、验证结果和最终收口状态。

## Task 1: 后端空响应重试回归测试

**Files:**
- Modify: `apps/agent-runtime/tests/test_story_engine_context.py`

- [ ] **Step 1: 写失败测试**

新增测试，复用现有 `StreamReasoningOnlyLengthThenSuccessGateway`，覆盖 `revise_chapter_pair()`：

```python
def test_revise_chapter_pair_retries_reasoning_only_length_before_generic_repair(self) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        capability_path = Path(tmp_dir) / "model_capabilities.json"
        capability_path.write_text(
            json.dumps(
                {
                    "defaults": {
                        "max_input_tokens": 200000,
                        "max_output_tokens": 10000,
                    },
                    "generation": {"max_tokens": 10000},
                    "models": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        engine = StoryEngine(
            Settings(
                openai_api_key="test-key",
                default_chat_model="mimo-v2.5-pro",
                MODEL_CAPABILITIES_PATH=str(capability_path),
                tasklog_root=str(Path(tmp_dir) / "tasklog"),
            )
        )
        payload = {
            "number": 1,
            "title": "修订后一章",
            "summary": "统一人物姓名与分数设定。",
            "content": "修订后的完整正文。",
        }
        gateway = StreamReasoningOnlyLengthThenSuccessGateway(payload)
        engine.gateway_client = gateway
        events: list[dict] = []
        engine.exchange_callback = events.append

        drafts = engine.revise_chapter_pair(
            current_pair=[payload],
            revision_comment="统一母亲姓名和高考分差。",
            spec={"mode": "fanfic", "creative_mode": "fanfic", "novel_size": "short", "model_id": "mimo-v2.5-pro"},
            story_plan={"working_title": "重启", "logline": "重生修复遗憾。", "chapter_plan": [{"number": 1, "title": "第一章"}]},
            completed_chapters=[],
            reference_text="",
            model="mimo-v2.5-pro",
        )

        self.assertEqual(drafts[0].summary, "统一人物姓名与分数设定。")
        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual(gateway.calls[0]["kwargs"].get("max_tokens"), 10000)
        self.assertEqual(gateway.calls[1]["kwargs"].get("max_tokens"), 10000)
        self.assertIn("不要输出分析过程", gateway.calls[1]["messages"][-1]["content"])
        self.assertNotIn("重新输出一个完整、可解析的 JSON 对象", gateway.calls[1]["messages"][-1]["content"])
        self.assertEqual([event.get("response_parse_failed") for event in events if event.get("response_parse_failed")], [])
        self.assertTrue(events[-1]["timing_details"][1]["is_retry"])
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py::StoryEngineContextTests::test_revise_chapter_pair_retries_reasoning_only_length_before_generic_repair -q
```

Expected: FAIL，原因是当前 `chapter-pair-revision` 没传 `empty_truncated_retry_prompt`，并且同预算 retry 不会触发。

## Task 2: 实现 chapter-pair-revision 空正文 retry

**Files:**
- Modify: `apps/agent-runtime/app/llm/story_engine.py`
- Test: `apps/agent-runtime/tests/test_story_engine_context.py`

- [ ] **Step 1: 增加章节修订 retry prompt**

在现有 `_VERIFICATION_TRUNCATED_RETRY_PROMPT` 附近增加：

```python
_CHAPTER_PAIR_TRUNCATED_RETRY_PROMPT = (
    "上一次章节修订响应被输出预算截断，且没有输出可解析正文。"
    "请停止分析，不要输出分析过程。"
    "请只返回最终章节 JSON；若有多章，返回 JSON 数组。"
    "每个章节必须包含 number、title、summary、content。"
    "summary 不超过 80 字；content 保留完整正文。"
    "不要输出 Markdown 代码围栏，不要解释，不要补充说明。"
)
```

- [ ] **Step 2: 允许同预算 retry**

给 `_complete_stream_json_with_cache()` 增加参数：

```python
empty_truncated_retry_allow_same_budget: bool = False,
```

更新 `_should_retry_empty_truncated_response()` 与 `_should_retry_non_empty_truncated_response()` 调用，逻辑为：

```python
if max_tokens is None:
    return True
if retry_max_tokens > max_tokens:
    return True
return allow_same_budget and retry_max_tokens == max_tokens
```

默认保持 `False`，避免影响 verification 现有测试语义。

- [ ] **Step 3: chapter-pair-revision 接入专用 retry**

在 `revise_chapter_pair()` 调用 `_complete_stream_json_with_cache()` 时传入：

```python
empty_truncated_retry_prompt=_CHAPTER_PAIR_TRUNCATED_RETRY_PROMPT,
empty_truncated_retry_max_tokens=chapter_max_tokens,
empty_truncated_retry_allow_same_budget=True,
```

- [ ] **Step 4: 增强 retry 日志**

在空正文截断 retry 的 warning 日志中增加：

```python
"content_chars=%s reasoning_chars=%s"
```

取值来自第一次 `timing_meta`。不要记录 prompt 或正文。

- [ ] **Step 5: 运行目标测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py::StoryEngineContextTests::test_revise_chapter_pair_retries_reasoning_only_length_before_generic_repair apps/agent-runtime/tests/test_story_engine_context.py::StoryEngineContextTests::test_verify_full_story_retries_reasoning_only_length_without_generic_repair apps/agent-runtime/tests/test_story_engine_context.py::StoryEngineContextTests::test_verify_full_story_retries_non_empty_length_before_repair -q
```

Expected: PASS。

## Task 3: 后端 LLM 缓存口径拆分

**Files:**
- Modify: `apps/agent-runtime/app/application/task_service/queries.py`
- Modify: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 写失败测试**

扩展 `test_workspace_endpoint_returns_llm_report_from_task_events()`，断言：

```python
self.assertEqual(report["runtime_response_cache_hit_count"], 1)
self.assertEqual(report["provider_prompt_cache_hit_count"], 1)
self.assertEqual(report["cache_hit_count"], 1)
```

测试数据中已有 `model.usage.cached_tokens=30` 与一个 `cache.hit` 事件，足够覆盖两类命中。

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py::ApiContextTests::test_workspace_endpoint_returns_llm_report_from_task_events -q
```

Expected: FAIL，缺少新字段。

- [ ] **Step 3: 实现字段统计**

在 `_build_llm_report()` 中新增变量：

```python
runtime_response_cache_hit_count = 0
provider_prompt_cache_hit_count = 0
```

在 `model.usage` 分支中：

```python
provider_cache_hit = usage["cached_tokens"] > 0 or usage["cache_read_input_tokens"] > 0
if provider_cache_hit:
    provider_prompt_cache_hit_count += 1
latest_usage = {
    ...,
    "provider_prompt_cache_hit": provider_cache_hit,
}
```

在 `context.history.updated/cache.hit` 分支中：

```python
if cache_hit:
    runtime_response_cache_hit_count += 1
    cache_hit_count += 1
```

返回值新增：

```python
"runtime_response_cache_hit_count": runtime_response_cache_hit_count,
"provider_prompt_cache_hit_count": provider_prompt_cache_hit_count,
```

- [ ] **Step 4: 运行后端相关测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_context.py apps/agent-runtime/tests/test_task_service_workspace.py -q
```

Expected: PASS。

## Task 4: 前端调试面板口径更新

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/features/task-run/debug-diagnostics.mjs`
- Modify: `apps/web/src/features/task-run/debug-panel.tsx`
- Modify: `apps/web/src/features/task-run/debug-diagnostics.test.mjs`

- [ ] **Step 1: 写失败测试**

在 `LLM 摘要包含调用、缓存、重试、修复、解析失败、模型与耗时信息` 中新增 report 字段：

```javascript
runtime_response_cache_hit_count: 1,
provider_prompt_cache_hit_count: 2,
```

新增断言：

```javascript
assert.equal(diagnostics.llm.runtimeResponseCacheHitCount, 1);
assert.equal(diagnostics.llm.providerPromptCacheHitCount, 2);
```

再在 “usage_total 为空对象时从事件用量兜底统计 token” 测试中断言：

```javascript
assert.equal(diagnostics.llm.providerPromptCacheHitCount, 1);
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd apps/web && npm test -- src/features/task-run/debug-diagnostics.test.mjs
```

Expected: FAIL，缺少新字段。

- [ ] **Step 3: 更新类型与诊断派生**

`LlmReport` 增加：

```typescript
runtime_response_cache_hit_count?: number;
provider_prompt_cache_hit_count?: number;
```

`deriveLlmFromEvents()` 增加：

```javascript
let providerPromptCacheHitCount = 0;
let runtimeResponseCacheHitCount = 0;
```

`model.usage` 事件中，若 `cachedTokens > 0 || cacheReadInputTokens > 0`，增加 provider 计数。

`cache.hit` 事件中增加 runtime response 计数。

`buildLlm()` 返回：

```javascript
runtimeResponseCacheHitCount: toInteger(report.runtime_response_cache_hit_count, eventSummary.runtimeResponseCacheHitCount),
providerPromptCacheHitCount: toInteger(report.provider_prompt_cache_hit_count, eventSummary.providerPromptCacheHitCount),
cacheHitCount: toInteger(report.cache_hit_count, eventSummary.runtimeResponseCacheHitCount),
```

- [ ] **Step 4: 更新面板文案**

在 `debug-panel.tsx` 中把指标改为：

```tsx
{ label: "响应缓存命中", value: formatNumber(llm.runtimeResponseCacheHitCount ?? llm.cacheHitCount) },
{ label: "供应商缓存命中", value: formatNumber(llm.providerPromptCacheHitCount) },
{ label: "缓存 tokens", value: formatNumber(llm.tokens?.cachedTokens || llm.tokens?.cacheReadInputTokens) },
```

保留 `缓存 tokens` 现有指标。

- [ ] **Step 5: 运行前端测试**

Run:

```bash
cd apps/web && npm test -- src/features/task-run/debug-diagnostics.test.mjs
```

Expected: PASS。

## Task 5: 诊断日志补强

**Files:**
- Modify: `apps/agent-runtime/app/llm/story_engine.py`
- Modify: `apps/agent-runtime/app/context/manager.py`
- Test: `apps/agent-runtime/tests/test_story_engine_context.py`
- Test: `apps/agent-runtime/tests/test_context_manager.py`

- [ ] **Step 1: 写流式响应缓存日志失败测试**

在 `apps/agent-runtime/tests/test_story_engine_context.py` 增加测试，使用 `self.assertLogs("app.llm.story_engine", level="DEBUG")` 包住一次 `_complete_stream_json_with_cache()` 成功调用。

断言日志包含：

```python
"流式响应缓存查询"
"流式响应缓存写入"
"exchange_label=chapter-01"
"model=K2.6"
```

不要断言完整 `cache_key`，只断言存在 `cache_key_prefix=`。

- [ ] **Step 2: 写上下文缓存日志失败测试**

在 `apps/agent-runtime/tests/test_context_manager.py` 增加测试，使用 `self.assertLogs("app.context.manager", level="DEBUG")` 或 `caplog` 记录两次相同 `build_snapshot()`。

断言日志包含：

```python
"上下文缓存查询"
"hit=False"
"hit=True"
"stage=drafting"
```

不要断言正文、instruction 或参考材料全文。

- [ ] **Step 3: 运行日志测试确认失败**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py::StoryEngineContextTests::test_stream_response_cache_logs_lookup_and_write apps/agent-runtime/tests/test_context_manager.py::ContextManagerTests::test_context_cache_logs_lookup_hit_and_miss -q
```

Expected: FAIL，当前没有这些明确日志。

- [ ] **Step 4: 流式响应缓存 lookup/write 日志**

本批只覆盖当前失败链路使用的流式结构化 JSON 路径：`_complete_stream_json_with_cache()`。非流式 `_complete_json_with_cache()` 暂不扩展，避免扩大 B 方案范围。

在 `_complete_stream_json_with_cache()` 缓存读取前后增加 debug 级日志：

```python
logger.debug(
    "流式响应缓存查询: stage=%s exchange_label=%s model=%s cache_key_prefix=%s max_tokens=%s hit=%s",
    stage,
    exchange_label,
    model,
    (cache_key or "")[:24],
    max_tokens,
    isinstance(cached_payload, dict),
)
```

写入缓存后增加：

```python
logger.debug(
    "流式响应缓存写入: stage=%s exchange_label=%s model=%s cache_key_prefix=%s",
    stage,
    exchange_label,
    model,
    (cache_key or "")[:24],
)
```

- [ ] **Step 5: 上下文缓存 lookup 日志**

在 `ContextManager.build_snapshot()` 中对 hit/miss 增加统一 info/debug 日志，包含：

```python
task_id, stage, model_id, cache_key, reference_count, memory_item_count
```

不要记录 `instruction`、正文、参考材料全文。

- [ ] **Step 6: 运行轻量后端测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_context_manager.py apps/agent-runtime/tests/test_story_engine_context.py -q
```

Expected: PASS。

## Task 6: 全量验证与手工核对

**Files:**
- No direct code edits.

- [ ] **Step 1: 后端目标测试**

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py apps/agent-runtime/tests/test_api_context.py apps/agent-runtime/tests/test_task_service_workspace.py apps/agent-runtime/tests/test_context_manager.py -q
```

Expected: PASS。

- [ ] **Step 2: 后端 lint**

Run:

```bash
uv run --project apps/agent-runtime ruff check apps/agent-runtime/
```

Expected: `All checks passed!`

- [ ] **Step 3: 前端测试**

Run:

```bash
cd apps/web && npm test -- src/features/task-run/debug-diagnostics.test.mjs
```

Expected: PASS。

- [ ] **Step 4: 前端 lint**

Run:

```bash
cd apps/web && npm run lint
```

Expected: PASS。

- [ ] **Step 5: 针对 task_593ea0bac8 诊断口径核对**

不直接修改已有任务数据。用可执行测试覆盖替代手工改数据：
- LLM 面板显示“响应缓存命中”和“供应商缓存命中”两个指标。
- `providerPromptCacheHitCount` 能从 `cached_tokens/cache_read_input_tokens` 得到非零值。
- 结构化 JSON 空正文 retry 的事件里 `timing_details` 有 `is_retry=true`。

Run:

```bash
uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_story_engine_context.py::StoryEngineContextTests::test_revise_chapter_pair_retries_reasoning_only_length_before_generic_repair -q
cd apps/web && npm test -- src/features/task-run/debug-diagnostics.test.mjs
```

Expected: 两条命令均 PASS。

## Task 7: worklog 与收口

**Files:**
- Modify: `worklog/active/LLM调用/20260702-01-task-593ea0bac8-trace-summary-cache-context.md`

- [ ] **Step 1: 更新当前问题文档**

记录：
- 修改文件列表。
- 测试命令与结果。
- 本批次未处理 C 方案“模型上下文窗口接口优先”的原因。
- 是否需要后续单独开 C 方案执行。

- [ ] **Step 2: 等待用户明确同意收口**

只有用户说“同意收口/同意提交/继续提交”等明确肯定后，才执行归档与提交。

- [ ] **Step 3: 归档 worklog**

按项目规则移动：

```text
worklog/active/LLM调用/20260702-01-task-593ea0bac8-trace-summary-cache-context.md
-> worklog/archive/LLM调用/20260702-01-task-593ea0bac8-trace-summary-cache-context.md
```

同步更新：
- `worklog/index.md`
- `worklog/history.md`

- [ ] **Step 4: 提交前 Git 核对**

Run:

```bash
pwd
git rev-parse --show-toplevel
git remote -v
git status --short
```

Expected:
- `pwd` 为 `/home/user01/WorkSpace/AgentProject` 或其子目录。
- `git rev-parse --show-toplevel` 为 `/home/user01/WorkSpace/AgentProject`。
- remote 指向目标仓库。
- `git status --short` 只包含本任务相关改动或已确认的既有改动。

- [ ] **Step 5: 中文提交**

提交信息建议：

```text
修复LLM调试观测与结构化输出空响应重试

- 拆分响应缓存与供应商缓存统计口径
- 为章节修订增加空正文截断重试
- 增强调试面板与后端诊断日志
```

## 风险与回退

- 风险：同预算 retry 可能仍被模型用于 reasoning。回退方式：保持只重试一次，失败后仍进入现有 parse_failed 诊断链，不无限重试。
- 风险：新增字段影响前端兼容。回退方式：保留 `cache_hit_count` 旧字段，前端使用新字段时做 fallback。
- 风险：日志过多。回退方式：缓存 lookup/write 使用 debug 级，异常与空正文 retry 使用 warning 级。
- 风险：章节修订 prompt 过短导致输出缺字段。回退方式：测试强制校验 `number/title/summary/content`，仍由现有 `ChapterDraft.model_validate()` 兜底。

## 完成标准

- `chapter-pair-revision` 空正文 `length/max_tokens` 能先走 JSON-only retry。
- LLM 调试面板不再把 Provider Prompt Cache 命中显示为“缓存命中 0”的误导口径。
- 后端 `llm_report` 同时提供运行时响应缓存命中与供应商 prompt cache 命中。
- 关键日志能通过 task_id、stage、exchange_label、cache_key 前缀定位问题，不泄露正文内容。
- 所有目标后端与前端测试通过。
