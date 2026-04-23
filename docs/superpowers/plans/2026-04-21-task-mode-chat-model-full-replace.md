# 任务模式全量替换与聊天模型切换修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将小说任务创建链路从旧 `mode` 全量替换为“创作类型 + 篇幅层级”新结构，并修复聊天页默认模型切换不生效、无法手动切换模型的问题。

**Architecture:** 后端先重构任务输入模型与规范化逻辑，把创作类型、篇幅层级、章节规划约束、单章字数下限提升为一等字段，再调整生成图与 StoryEngine 使用这些字段驱动章节规划与风格实例注入。前端创建页同步切换到新字段结构，聊天链路独立修复为“运行时默认模型实时解析 + 会话级模型选择”。

**Tech Stack:** FastAPI, Pydantic, LangGraph, Next.js, React, TypeScript, unittest

---

## 文件结构与职责

**后端任务建模**
- 修改: `apps/agent-runtime/app/domain/models.py`
  - 废弃旧 `TaskMode` 作为主输入枚举，引入 `CreativeMode`、`NovelSize`
  - 为 `TaskInput` / `TaskCreateRequest` / `TaskRecord` 增加新字段
- 修改: `apps/agent-runtime/app/application/task_service.py`
  - 统一读取新字段，确保任务创建、恢复、展示都使用新语义
- 修改: `apps/agent-runtime/app/storage/db_models.py`
  - 视当前持久化字段需要补充新列或兼容存储映射
- 修改: `apps/agent-runtime/app/storage/db_repository.py`
  - 确保持久化层读写新字段

**后端工作流与生成**
- 修改: `apps/agent-runtime/app/graph/main_graph.py`
  - 规范化新字段
  - 计算 `chapter_count_range`、`chapter_word_min`、章节批次策略
- 修改: `apps/agent-runtime/app/llm/story_engine.py`
  - 用新字段改写大纲提示词、章节提示词、字数规则、章节规划约束
- 修改: `apps/agent-runtime/app/novel_skills/service.py`
  - 为 `fanfic` / `style_remix` 分流风格实例语义
- 修改: `apps/agent-runtime/app/style_profiles/service.py`
  - 视需要补充“世界观约束摘要”和“文风摘要”双通道输出

**聊天链路**
- 修改: `apps/agent-runtime/app/api/routes.py`
  - 去掉聊天默认模型闭包缓存，改为请求时实时解析
- 修改: `apps/web/src/features/chat/chat-client.tsx`
  - 增加聊天模型选择、默认模型刷新、会话级模型状态
- 修改: `apps/web/src/lib/chat-storage.ts`
  - 持久化会话模型
- 修改: `apps/web/src/lib/api.ts`
  - 确保聊天接口显式透传模型字段

**前端任务创建与展示**
- 修改: `apps/web/src/lib/types.ts`
  - 切换到 `creative_mode` / `novel_size` / `chapter_word_min`
- 修改: `apps/web/src/features/task-create/create-task-client.tsx`
  - 把单一“任务模式”改为“创作类型 + 篇幅层级”
  - `fanfic` / `style_remix` 都允许实例选择
- 修改: `apps/web/src/features/task-run/task-run-client.tsx`
- 修改: `apps/web/src/features/task-archive/archive-list-client.tsx`
- 修改: `apps/web/src/features/task-archive/archive-detail-client.tsx`
  - 展示新模式标签

**测试**
- 修改: `apps/agent-runtime/tests/test_graph_chapter_pair_loop.py`
- 修改: `apps/agent-runtime/tests/test_graph_style_profiles.py`
- 修改: `apps/agent-runtime/tests/test_story_engine_context.py`
- 修改: `apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py`
- 修改: `apps/agent-runtime/tests/test_api_context.py`
- 新增或修改: 聊天模型切换相关 API / 前端测试

---

## Agent Team 分工

### Agent 1: 后端任务模型与规范化

**目标:** 完成任务输入模型全量替换，确保新任务创建、存储、读取全部使用新字段。

**Files:**
- Modify: `apps/agent-runtime/app/domain/models.py`
- Modify: `apps/agent-runtime/app/application/task_service.py`
- Modify: `apps/agent-runtime/app/storage/db_models.py`
- Modify: `apps/agent-runtime/app/storage/db_repository.py`
- Test: `apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 写失败测试，约束新建任务请求结构**

```python
def test_create_task_uses_creative_mode_and_novel_size(self):
    payload = {
        "creative_mode": "fanfic",
        "novel_size": "long",
        "chapter_word_min": 2400,
        "prompt": "写都市医生修罗场长篇",
        "style_profile_id": "example-style",
        "model_id": "gpt-5.4",
    }
    response = self.client.post("/api/tasks", json=payload)
    self.assertEqual(response.status_code, 200)
```

- [ ] **Step 2: 跑失败测试确认旧模型不再满足**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_api_context tests.test_settings_and_gateway_fail_fast`

Expected: 至少有请求字段或校验逻辑失败。

- [ ] **Step 3: 最小实现新枚举与请求模型**

```python
class CreativeMode(str, Enum):
    ORIGINAL = "original"
    FANFIC = "fanfic"
    STYLE_REMIX = "style_remix"

class NovelSize(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
```

- [ ] **Step 4: 让任务创建、持久化、查询全部写入新字段**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_api_context tests.test_settings_and_gateway_fail_fast`

Expected: 新请求模型相关测试通过。

- [ ] **Step 5: 提交本组改动**

```bash
git add apps/agent-runtime/app/domain/models.py apps/agent-runtime/app/application/task_service.py apps/agent-runtime/app/storage/db_models.py apps/agent-runtime/app/storage/db_repository.py apps/agent-runtime/tests/test_api_context.py apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py
git commit -m "重构任务输入模型为创作类型与篇幅层级"
```

### Agent 2: 工作流章节规划与字数规则

**目标:** 用 `creative_mode`、`novel_size`、`chapter_word_min` 驱动章节规划、章节批次和提示词。

**Files:**
- Modify: `apps/agent-runtime/app/graph/main_graph.py`
- Modify: `apps/agent-runtime/app/llm/story_engine.py`
- Test: `apps/agent-runtime/tests/test_graph_chapter_pair_loop.py`
- Test: `apps/agent-runtime/tests/test_story_engine_context.py`

- [ ] **Step 1: 写失败测试，约束长中短篇章节范围与单章字数下限**

```python
def test_long_novel_requires_chapter_count_above_400(self):
    spec = build_normalized_spec({
        "creative_mode": "original",
        "novel_size": "long",
        "chapter_word_min": 3000,
        "prompt": "写长篇小说",
    })
    self.assertEqual(spec["chapter_count_range"]["min"], 401)
```

- [ ] **Step 2: 写失败测试，约束风格复刻首批两章、后续单章**

```python
def test_style_remix_uses_pair_then_single_batches(self):
    self.assertEqual(engine.generated_batch_sizes, [2, 1, 1, 1])
```

- [ ] **Step 3: 在规范化层实现章节范围与单章字数规则**

```python
def _chapter_count_range(novel_size: str) -> dict[str, int | None]:
    if novel_size == "short":
        return {"min": 8, "max": 80}
    if novel_size == "medium":
        return {"min": 80, "max": 400}
    return {"min": 401, "max": None}
```

- [ ] **Step 4: 在 StoryEngine 提示词中显式要求主 agent 给出 `planned_chapter_count`**

```python
"你必须先确定 planned_chapter_count，并保证其落在 chapter_count_range 内。"
```

- [ ] **Step 5: 将单章目标字数表达从总字数切换为“下限 + 浮动区间”**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_graph_chapter_pair_loop tests.test_story_engine_context`

Expected: 章节批次与 prompt 注入测试通过。

- [ ] **Step 6: 提交本组改动**

```bash
git add apps/agent-runtime/app/graph/main_graph.py apps/agent-runtime/app/llm/story_engine.py apps/agent-runtime/tests/test_graph_chapter_pair_loop.py apps/agent-runtime/tests/test_story_engine_context.py
git commit -m "重构章节规划与单章字数约束"
```

### Agent 3: 风格实例分流

**目标:** 让 `fanfic` 与 `style_remix` 都支持风格实例，但注入语义不同。

**Files:**
- Modify: `apps/agent-runtime/app/novel_skills/service.py`
- Modify: `apps/agent-runtime/app/style_profiles/service.py`
- Modify: `apps/agent-runtime/app/graph/main_graph.py`
- Test: `apps/agent-runtime/tests/test_graph_style_profiles.py`
- Test: `apps/agent-runtime/tests/test_novel_skills.py`

- [ ] **Step 1: 写失败测试，约束 fanfic 与 style_remix 的 runtime context 分流**

```python
def test_fanfic_profile_builds_canon_guidance(self):
    context = service.build_runtime_context(mode="fanfic", style_profile_id="douluo")
    self.assertIn("世界观", context["canon_guidance"])
```

- [ ] **Step 2: 写失败测试，约束 style_remix 仍输出文风 guidance**

```python
def test_style_remix_profile_builds_style_guidance(self):
    context = service.build_runtime_context(mode="style_remix", style_profile_id="douluo")
    self.assertIn("语言规则", context["style_guidance"])
```

- [ ] **Step 3: 在 style profile service 中提供双摘要接口**

```python
return {
    "canon_summary": "...",
    "style_summary": "...",
}
```

- [ ] **Step 4: 在 runtime context 中按创作类型分流字段**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_graph_style_profiles tests.test_novel_skills`

Expected: 两种模式都能选实例，但注入内容不同。

- [ ] **Step 5: 提交本组改动**

```bash
git add apps/agent-runtime/app/novel_skills/service.py apps/agent-runtime/app/style_profiles/service.py apps/agent-runtime/app/graph/main_graph.py apps/agent-runtime/tests/test_graph_style_profiles.py apps/agent-runtime/tests/test_novel_skills.py
git commit -m "重构风格实例在同人与复刻中的分流语义"
```

### Agent 4: 前端创建页与展示页全量替换

**目标:** 创建页改成新字段结构，展示页同步显示新标签。

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/features/task-create/create-task-client.tsx`
- Modify: `apps/web/src/features/task-run/task-run-client.tsx`
- Modify: `apps/web/src/features/task-archive/archive-list-client.tsx`
- Modify: `apps/web/src/features/task-archive/archive-detail-client.tsx`

- [ ] **Step 1: 写前端类型草案并让旧字段编译失败**

```ts
export type CreativeMode = "original" | "fanfic" | "style_remix";
export type NovelSize = "short" | "medium" | "long";
```

- [ ] **Step 2: 将创建页模式控件拆成两个选择器**

```tsx
<TextField select label="创作类型" />
<TextField select label="篇幅规模" />
```

- [ ] **Step 3: 将 `target_words` 替换为 `chapter_word_min` 文案与提交字段**

```tsx
label="单章字数下限"
helperText="系统会在此基础上按章节需要上浮 10%-30%"
```

- [ ] **Step 4: 让 fanfic 与 style_remix 都显示风格实例选择器**

- [ ] **Step 5: 更新运行页、归档页的模式展示映射**

Run: `cd apps/web && npm run build`

Expected: 前端构建通过，无旧 `mode` 类型残留报错。

- [ ] **Step 6: 提交本组改动**

```bash
git add apps/web/src/lib/types.ts apps/web/src/lib/api.ts apps/web/src/features/task-create/create-task-client.tsx apps/web/src/features/task-run/task-run-client.tsx apps/web/src/features/task-archive/archive-list-client.tsx apps/web/src/features/task-archive/archive-detail-client.tsx
git commit -m "重构前端任务创建与展示模式结构"
```

### Agent 5: 聊天模型切换修复

**目标:** 修复默认模型切换不生效，并支持聊天页手动切换模型。

**Files:**
- Modify: `apps/agent-runtime/app/api/routes.py`
- Modify: `apps/web/src/features/chat/chat-client.tsx`
- Modify: `apps/web/src/lib/chat-storage.ts`
- Modify: `apps/web/src/lib/api.ts`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 写失败测试，约束默认模型更新后聊天接口立即使用新模型**

```python
def test_chat_stream_uses_runtime_default_model(self):
    update_default_model("glm-5.1")
    response = self.client.post("/api/chat/completions", json={"messages": [...]})
    self.assertEqual(response.json()["model"], "glm-5.1")
```

- [ ] **Step 2: 去掉路由级 `_default_model` 闭包缓存**

```python
resolved_model = payload.model or engine.resolve_model(None) or ""
```

- [ ] **Step 3: 在聊天页新增模型选择状态并随会话持久化**

```ts
type StoredConversation = {
  model?: string;
}
```

- [ ] **Step 4: 发送聊天请求时显式透传当前会话模型**

Run: `cd apps/agent-runtime && uv run python -m unittest tests.test_api_context`

Run: `cd apps/web && npm run build`

Expected: 默认模型切换与聊天页手动模型选择都能通过回归。

- [ ] **Step 5: 提交本组改动**

```bash
git add apps/agent-runtime/app/api/routes.py apps/web/src/features/chat/chat-client.tsx apps/web/src/lib/chat-storage.ts apps/web/src/lib/api.ts apps/agent-runtime/tests/test_api_context.py
git commit -m "修复聊天模型切换与会话级模型选择"
```

---

## 集成与全链路验证

### Task 6: 后端回归

**Files:**
- Test: `apps/agent-runtime/tests/test_graph_chapter_pair_loop.py`
- Test: `apps/agent-runtime/tests/test_graph_style_profiles.py`
- Test: `apps/agent-runtime/tests/test_story_engine_context.py`
- Test: `apps/agent-runtime/tests/test_settings_and_gateway_fail_fast.py`
- Test: `apps/agent-runtime/tests/test_api_context.py`

- [ ] **Step 1: 运行聚焦测试**

Run:

```bash
cd apps/agent-runtime
uv run python -m unittest \
  tests.test_graph_chapter_pair_loop \
  tests.test_graph_style_profiles \
  tests.test_story_engine_context \
  tests.test_settings_and_gateway_fail_fast \
  tests.test_api_context
```

Expected: 全部通过。

- [ ] **Step 2: 修正失败断言与兼容残留**

- [ ] **Step 3: 记录新的章节范围、风格实例、聊天模型行为**

### Task 7: 前端与接口联调

**Files:**
- Modify if needed: `apps/web/src/features/task-create/create-task-client.tsx`
- Modify if needed: `apps/web/src/features/chat/chat-client.tsx`

- [ ] **Step 1: 运行前端构建**

Run: `cd apps/web && npm run build`

Expected: 构建通过。

- [ ] **Step 2: 启动服务并手测关键链路**

Run:

```bash
./start.sh
```

Check:
- 创建页可选“全新原创 / 同人创作 / 风格复刻”
- 创建页可选“短篇 / 中篇 / 长篇”
- `fanfic` / `style_remix` 都可选实例
- 聊天页切换模型后请求使用新模型
- 设置页切默认模型后，新会话聊天默认值更新

- [ ] **Step 3: 如手测通过，整理最终归档与提交**

---

## 风险与注意事项

- 全量替换会影响历史任务展示，实施时必须决定历史旧 `mode` 在展示层如何映射，否则归档页会出现空值或英文旧标识。
- `long` 的边界按你的定义是 400 章以上，实施时统一采用 `min = 401`，避免和 `medium` 的 400 冲突。
- `chapter_word_min` 是单章下限，不应再在任意地方被解释成全文总字数。
- `fanfic` 的实例注入必须偏设定约束，不能直接复用 `style_remix` 的“文风模仿”提示，否则模式语义会塌陷。
- 聊天模型修复要和任务模型替换隔离提交，便于回退。

---

## 推荐执行顺序

1. Agent 1 完成后端任务模型替换
2. Agent 2 完成章节规划与字数规则
3. Agent 3 完成风格实例分流
4. Agent 4 完成前端创建页与展示页
5. Agent 5 完成聊天模型切换修复
6. 统一回归测试与联调
