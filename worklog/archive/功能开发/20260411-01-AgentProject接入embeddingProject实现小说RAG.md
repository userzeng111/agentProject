# 问题标题

AgentProject 接入 embeddingProject 实现小说编写与问答 RAG

## 用户原始诉求

采用 agent team 分配任务并自动执行：`/home/user01/WorkSpace/AgentProject` 是主项目，`embeddingProject` 是提供功能支持的子项目，用于做 RAG。需要将 `embeddingProject` 接入当前 `AgentProject`，为小说编写和问答提供 RAG 能力。子项目已经实现 RAG 工具链，并带有 CLI 测试；其中的 LLM 仅用于测试。`AgentProject` 主项目在正式接入时仍需使用用户现有 API 的 LLM。

## 当前状态

已完成：主项目与子项目结构分析、RAG 适配层接入、小说任务流接入、聊天问答接入、后端全量测试验证均已完成。后续新增的“语料库隔离与设置同步入口”需求已拆分为独立问题单独跟进。

## 当前已知约束

- 需要使用 agent team 进行并行分析与后续执行。
- 在讨论完成并得到用户明确同意前，不得修改业务代码。
- `embeddingProject` 现有 LLM 仅用于测试，正式接入应复用 `AgentProject` 现有 API LLM。
- 本次目标包含两类能力：小说编写 RAG、问答 RAG。

## 当前分析结论

### 主项目接入点

- 小说生成主链路为：`/api/tasks` -> `TaskService` -> `main_graph` -> `StoryEngine` -> `OpenAICompatibleGatewayClient`。
- 聊天问答主链路为：`/api/chat/stream` 与 `/api/chat/completions`，前端入口为 `apps/web/src/app/chat/page.tsx`。
- 主项目最佳接入层不是直接改 LLM 网关，而是后端“上下文装配层”，即 `main_graph.py` 中 `prepare_outline_context / prepare_chapter_pair_context` 与聊天接口进入网关前的消息构造层。

### 子项目可复用边界

- `embeddingProject` 可拆为三层：建索引、检索、检索后拼装回答。
- 与 `llama.cpp` 强耦合的是 `create_embedder / create_generator` 及对应运行时实现。
- 最适合复用的是“检索 + 上下文拼装”能力：`chunk_text`、`index_documents`、`search_documents`、`select_contexts`，而不是直接复用其本地生成器。

### 兼容风险

- RAG 结果必须进入主项目现有 `references / memory_items / request_messages`，否则上下文缓存与响应缓存可能错误命中。
- 任务恢复依赖 `context` 快照与历史文件，RAG 上下文若不持久化，恢复后会丢失检索依据。
- `embeddingProject` 当前依赖 `faiss-cpu`、`llama-cpp-python`，且 Python 版本约束与主项目不一定一致；正式接入时应避免把测试型生成器依赖硬塞入主运行链。

## 待确认设计问题

- 小说 RAG 是否只用于“参考素材增强”，还是要参与“世界观/角色设定知识库”的长期检索。
- 聊天页 RAG 是否需要独立知识库管理入口，还是先复用后端固定索引。
- 索引更新是本轮同时接入，还是先只做查询接入、后续再补管理能力。

## 用户已确认范围

- 选项：`C`
- 范围：同时接入“小说任务流 RAG + 聊天问答 RAG”
- 暂不包含：索引管理服务化入口（建索引/更新/删除先不改为主项目 API）

## 当前确认方案

- 用户已选择方案 `2`
- 方案内容：在主项目内新增 `RAG` 适配层，复用 `embeddingProject` 的“检索 + 上下文拼装”能力；小说任务流与聊天问答共用该层，最终生成仍统一走主项目现有 API LLM。

## 已执行实现

### 新增能力

- 在 `apps/agent-runtime/app/rag/` 新增 `RAG` 配置与服务层：
  - `config.py`：默认读取 `embeddingProject/artifacts/...`，同时支持环境变量覆盖。
  - `service.py`：封装检索、上下文裁剪、聊天消息增强、小说上下文参考材料生成，以及无索引自动降级。
- 小说任务流已接入 RAG：
  - `main_graph.py` 在大纲上下文与章节上下文准备阶段注入检索结果。
  - `task_service.py` 在恢复审核场景重新构造上下文时，同样补入 RAG 参考，避免恢复后丢检索依据。
- 聊天问答已接入 RAG：
  - `routes.py` 在 `/api/chat/stream` 与 `/api/chat/completions` 调用网关前先做检索，再将结果注入消息。
  - `domain/models.py` 为聊天请求增加最小 RAG 控制字段，默认开启。

### 兼容性处理

- 无索引、无命中、依赖未安装等情况下，RAG 自动降级为空结果，不阻断现有聊天与小说任务流。
- 保持主项目现有 API LLM 为唯一生成通道，未接入 `embeddingProject` 的本地测试型生成器。
- 修正了动态审核桥接层的启用条件，仅当网关对象具备 `complete_stream_sync` 时才启用，避免测试与非兼容网关误入动态审核桥接。

## 验证结果

- 新增并通过：
  - `tests/test_rag_service.py`
  - `tests/test_graph_context.py` 中的 RAG 上下文注入用例
  - `tests/test_api_context.py` 中的聊天 RAG 注入用例
- 全量后端测试命令：
  - `./.venv/bin/pytest -q`
- 结果：
  - `62 passed in 3.47s`

## 归档说明

- 后续新增的“小说 RAG 语料库隔离与设置同步入口”需求已拆分到：
  - `worklog/active/功能开发/20260411-02-小说RAG语料库隔离与设置同步入口.md`
- 本归档记录仅覆盖本次已完成的“主项目接入 embeddingProject 实现小说编写与问答 RAG”工作。
