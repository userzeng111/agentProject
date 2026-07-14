# 模型兼容性验证功能设计

## 1. 背景

当前模型目录会合并网关返回模型与本地模型画像。网关返回且本地注册表中没有画像的模型会被标记为 `metadata.compatibility = "unverified"`，并且 `capabilities.features.novel_task_supported = false`。因此 `K2.7` 虽然能出现在 AI 对话的网关模型列表中，但在设为默认模型或用于小说任务流时会被 `ensure_novel_generation_model_supported()` 阻断。

用户希望把“兼容性验证”放进 AI 对话中：用户选择一个未验证模型后，系统提示可运行验证；用户手动点击“运行验证”后，后端发起一组可观测验证。如果模型在对话过程中能返回推理相关信号、能正确接收上下文、能流式输出、能按小说任务所需格式返回结构化内容，就可以把该模型标记为已验证；如果失败，页面要告诉用户失败原因。

## 2. 已确认决策

- 主入口采用 A 方案：AI 对话页内增加右侧“模型验证”面板。
- 辅助入口采用 C 方案：当切换默认模型或小说任务模型失败时，提供“去 AI 对话验证”的引导。
- 暂不把 B 方案“设置页模型实验室”作为首批主入口。
- 验证不暴露模型隐藏思考链。页面展示“推理摘要 / 推理事件 / 推理信号是否存在”，不要求展示完整内部思考。
- 验证通过后需要持久化到本地模型兼容性覆盖文件，使模型目录刷新后仍显示为已验证。
- 首批范围限定为单模型、用户手动触发、单机本地覆盖；不做批量验证和后台自动重验。

## 3. 目标

首批功能要解决以下问题：

- 用户能在 AI 对话页选择 `K2.7` 这类网关新模型并运行兼容性验证。
- 页面能显示每个验证项的状态、证据摘要、失败原因和建议动作。
- 验证过程尽量复用现有聊天流式能力，让用户看到真实对话输出。
- 验证通过后，模型目录把该模型标记为 `verified`，并允许用于小说任务流。
- 验证失败后，模型保持 `unverified`，并保存最近失败报告，供用户排查协议、上下文、JSON、流式或推理信号问题。
- 模型切换失败提示能引导用户到 AI 对话页并预选待验证模型。

## 4. 非目标

首批不做：

- 不展示完整隐藏思考链或完整 provider raw response。
- 不做在线模型评分榜、模型推荐系统或自动选择最佳模型。
- 不做批量验证所有模型。
- 不做定时后台重验证。
- 不做权限系统或多用户隔离。
- 不把验证功能做成独立“设置页模型实验室”。
- 不修改供应商 API 配置方式。

## 5. 兼容性定义

一个模型要被标记为“可用于小说任务流”，首批必须通过以下硬性验证项。

### 5.1 网关可见性

模型必须出现在当前 `/api/models?refresh=true` 聚合结果中，且 `metadata.source` 包含 `gateway`。

失败原因示例：

- `模型未出现在网关返回列表中，请检查 LLM_BASE_URL、LLM_API_KEY 或供应商模型权限。`

### 5.2 流式输出

使用该模型调用 `/api/chat/stream` 或新的验证流端点时，必须至少收到一个 `chat.chunk`，并最终收到 `chat.done`。

失败原因示例：

- `未收到流式 chunk，模型可能不支持当前协议的流式响应。`
- `流式响应中断：<网关错误摘要>`

### 5.3 内容输出

验证请求必须得到非空正文，且正文要包含指定上下文哨兵值。哨兵值由后端生成，例如 `CTX-<短随机值>`，通过 system/user 消息注入。模型必须在最终回答或结构化 JSON 中回显该哨兵值。

该项证明模型实际接收并使用了系统注入的上下文，不证明模型“理解质量”。

失败原因示例：

- `模型有输出，但未回显上下文哨兵，可能没有正确接收系统上下文。`

### 5.4 推理信号

首批把“思考链”实现为可观测推理信号，而不是完整隐藏思考链。通过条件为至少满足一个：

- 流式 chunk 中出现 `reasoning_content`。
- 非流式响应 message 中出现 `reasoning_content`。
- provider 返回可识别的推理事件，并被后端归一化为 `reasoning_signal=true`。

验证报告只保存是否出现、字符长度、事件计数等元数据，不保存、不展示 `reasoning_content` 原文片段，也不生成来自隐藏推理原文的摘要。若 provider 明确返回可公开展示的 reasoning summary 字段，后续可另行设计；首批不使用。

失败原因示例：

- `未收到 reasoning_content 或可识别推理事件。该模型可聊天，但不满足当前小说任务流的推理信号要求。`

### 5.5 结构化 JSON

模型必须按验证 prompt 返回可解析 JSON，且字段满足最小 schema：

```json
{
  "context_marker": "CTX-xxxx",
  "outline": [
    {"title": "章节标题", "goal": "章节目标"}
  ],
  "risk_flags": []
}
```

失败原因示例：

- `模型输出不是合法 JSON。`
- `JSON 缺少 outline 或 context_marker 字段。`

### 5.6 小说任务最小能力

模型必须能根据短篇小说任务指令输出一段中文大纲或章节片段，且正文非空、中文字符占比合理、未触发网关错误。

首批只验证“可运行与格式兼容”，不判断文学质量。

失败原因示例：

- `模型返回内容为空。`
- `模型输出不符合中文小说任务最小格式。`

## 6. 验证结果状态

验证结果分为：

- `verified`：所有硬性验证项通过，可用于小说任务流。
- `failed`：至少一个硬性验证项失败。
- `running`：验证进行中。
- `unverified`：从未验证或验证记录不可用。

模型目录中 `metadata.compatibility` 仍使用现有值：

- `verified`
- `unverified`

额外新增 `metadata.validation` 摘要：

```json
{
  "status": "verified",
  "validated_at": "2026-06-30T10:00:00Z",
  "validator_version": "2026-06-30",
  "summary": "流式、上下文、推理信号、JSON 与小说最小能力均通过",
  "last_error": ""
}
```

### 6.1 检查项 ID

前后端、SSE 和持久化统一使用以下检查项 ID：

| ID | 名称 | 对应章节 |
| --- | --- | --- |
| `gateway_visible` | 网关可见 | 5.1 |
| `streaming` | 流式输出 | 5.2 |
| `content_output` | 内容输出 | 5.3 / 5.6 |
| `reasoning_signal` | 推理信号 | 5.4 |
| `context_echo` | 上下文回显 | 5.3 |
| `json_schema` | 结构化 JSON | 5.5 |
| `novel_minimum` | 小说任务最小能力 | 5.6 |

检查项状态枚举：

- `pending`
- `running`
- `passed`
- `failed`
- `skipped`

## 7. 后端设计

### 7.1 本地持久化

新增本地文件：

- `tasklog/model_compatibility.json`

结构：

```json
{
  "version": 1,
  "models": {
    "K2.7": {
      "status": "verified",
      "validated_at": "2026-06-30T10:00:00Z",
      "validator_version": "2026-06-30",
      "checks": [
        {"id": "gateway_visible", "status": "passed", "summary": "模型来自网关"},
        {"id": "streaming", "status": "passed", "summary": "收到 8 个 chunk"},
        {"id": "content_output", "status": "passed", "summary": "收到非空正文"},
        {"id": "reasoning_signal", "status": "passed", "summary": "收到推理信号元数据"},
        {"id": "context_echo", "status": "passed", "summary": "已回显上下文哨兵"},
        {"id": "json_schema", "status": "passed", "summary": "JSON 可解析"},
        {"id": "novel_minimum", "status": "passed", "summary": "中文小说片段非空"}
      ],
      "failure_reason": "",
      "evidence": {
        "chunk_count": 8,
        "reasoning_chars": 126,
        "content_chars": 312,
        "context_marker_seen": true
      }
    }
  }
}
```

只保存摘要证据，不保存完整 prompt、完整回答或完整推理内容。

### 7.2 模型目录合并

`ModelCatalogService` 在 `_build_model_item()` 后应用本地兼容性覆盖：

- 如果覆盖记录 `status = "verified"` 且模型来源包含 `gateway`：
  - `metadata.compatibility = "verified"`
  - `capabilities.features.novel_task_supported = true`
  - `metadata.validation` 填入验证摘要
- 如果覆盖记录 `status = "failed"`：
  - 保持 `metadata.compatibility = "unverified"`
  - `capabilities.features.novel_task_supported = false`
  - `metadata.validation` 填入失败摘要

覆盖记录不能让纯 `registry` 且网关不可见的模型变成可用模型。

### 7.3 验证服务

新增 `ModelCompatibilityService`，职责：

- 读取和保存 `tasklog/model_compatibility.json`。
- 运行验证步骤。
- 复用 `OpenAICompatibleGatewayClient.complete_stream()`。
- 生成检查项状态、失败原因和摘要证据。
- 为 `ModelCatalogService` 提供只读覆盖查询。

验证服务不承担模型推荐、评分或 UI 状态管理。

### 7.4 API 路由与模型 ID 编码

为避免模型 ID 中出现 `/`、空格、冒号等字符导致 FastAPI path 参数匹配歧义，首批接口不把模型 ID 放入路径，统一放入 JSON body 或 query 参数。

#### `GET /api/model-validation`

查询最近一次验证结果。

Query 参数：

- `model_id`: 必填，URL encoded。

#### `POST /api/model-validation/stream`

启动一次验证，返回 SSE。

JSON body：

```json
{
  "model_id": "K2.7"
}
```

#### `DELETE /api/model-validation`

清除该模型本地验证覆盖。

JSON body：

```json
{
  "model_id": "K2.7"
}
```

### 7.5 SSE 契约

所有 SSE 事件的 `data` 都是 JSON。

通用检查项结构：

```json
{
  "id": "streaming",
  "label": "流式输出",
  "status": "passed",
  "summary": "收到 8 个 chunk",
  "failure_reason": "",
  "evidence": {
    "chunk_count": 8
  }
}
```

通用报告结构：

```json
{
  "model_id": "K2.7",
  "status": "verified",
  "validated_at": "2026-06-30T10:00:00Z",
  "validator_version": "2026-06-30",
  "summary": "流式、上下文、推理信号、JSON 与小说最小能力均通过",
  "failure_reason": "",
  "checks": [
    {
      "id": "streaming",
      "label": "流式输出",
      "status": "passed",
      "summary": "收到 8 个 chunk",
      "failure_reason": "",
      "evidence": {"chunk_count": 8}
    }
  ],
  "evidence": {
    "chunk_count": 8,
    "reasoning_chars": 126,
    "content_chars": 312,
    "context_marker_seen": true
  }
}
```

#### `validation.started`

```json
{
  "model_id": "K2.7",
  "run_id": "validation_xxx",
  "validator_version": "2026-06-30",
  "status": "running"
}
```

#### `validation.check`

```json
{
  "model_id": "K2.7",
  "run_id": "validation_xxx",
  "check": {
    "id": "streaming",
    "label": "流式输出",
    "status": "passed",
    "summary": "收到 8 个 chunk",
    "failure_reason": "",
    "evidence": {
      "chunk_count": 8
    }
  }
}
```

#### `validation.chat_chunk`

```json
{
  "model_id": "K2.7",
  "run_id": "validation_xxx",
  "content": "可展示给用户的正文增量",
  "reasoning_signal": true,
  "reasoning_chars_delta": 24,
  "usage": {
    "total_tokens": 123
  }
}
```

`validation.chat_chunk` 不包含 `reasoning_content` 原文。

#### `validation.done`

```json
{
  "model_id": "K2.7",
  "run_id": "validation_xxx",
  "status": "verified",
  "report": {
    "model_id": "K2.7",
    "status": "verified",
    "validated_at": "2026-06-30T10:00:00Z",
    "validator_version": "2026-06-30",
    "summary": "流式、上下文、推理信号、JSON 与小说最小能力均通过",
    "failure_reason": "",
    "checks": [
      {
        "id": "streaming",
        "label": "流式输出",
        "status": "passed",
        "summary": "收到 8 个 chunk",
        "failure_reason": "",
        "evidence": {"chunk_count": 8}
      }
    ],
    "evidence": {
      "chunk_count": 8,
      "reasoning_chars": 126,
      "content_chars": 312,
      "context_marker_seen": true
    }
  }
}
```

#### `validation.error`

```json
{
  "model_id": "K2.7",
  "run_id": "validation_xxx",
  "status": "failed",
  "message": "未收到推理信号",
  "check_id": "reasoning_signal",
  "report": {
    "model_id": "K2.7",
    "status": "failed",
    "validated_at": "2026-06-30T10:00:00Z",
    "validator_version": "2026-06-30",
    "summary": "验证失败",
    "failure_reason": "未收到推理信号",
    "checks": [
      {
        "id": "reasoning_signal",
        "label": "推理信号",
        "status": "failed",
        "summary": "未收到推理信号",
        "failure_reason": "未收到 reasoning_content 或可识别推理事件",
        "evidence": {"reasoning_chars": 0}
      }
    ],
    "evidence": {
      "chunk_count": 8,
      "reasoning_chars": 0,
      "content_chars": 312,
      "context_marker_seen": true
    }
  }
}
```

失败验证会持久化 `status = "failed"` 覆盖，用于展示最近失败原因，但不会放行小说任务流。用户主动取消验证不持久化覆盖，只在当前前端会话显示“已取消”。

## 8. 前端设计

### 8.1 AI 对话页布局

在 `ChatClient` 保留现有结构：

- 左侧：会话列表。
- 中间：聊天消息流。
- 右侧：新增“模型验证”面板，桌面端常驻，移动端通过抽屉打开。

右侧面板内容：

- 当前模型名称与兼容状态。
- 验证按钮：`运行验证` / `重新验证` / `清除验证`。
- 检查项列表：
  - 网关可见
  - 流式输出
  - 内容输出
  - 推理信号
  - 上下文回显
  - 结构化 JSON
  - 小说任务最小能力
- 每项状态：等待、运行中、通过、失败。
- 每项证据摘要和失败原因。
- 验证通过后的提示：`该模型已可用于小说任务流。`

### 8.2 聊天消息区

验证运行时，在中间消息流插入一组“验证会话消息”：

- 用户消息：`运行模型兼容性验证：<model_id>`。
- 助手消息：真实流式输出正文。
- 验证专用元数据区：显示“推理信号元数据”，例如 `收到推理信号，累计 126 字符`。该区域不复用普通聊天的 `reasoning_content` 展示，不显示完整隐藏推理，也不显示来自隐藏推理原文的摘要。

普通聊天仍按现有逻辑运行，不强制打开验证面板。

### 8.3 模型选择器

聊天页模型选择器继续显示所有 `gateway` / `gateway+registry` 模型，但补充状态标签：

- 已验证
- 未验证
- 最近验证失败

未验证模型仍可聊天，但用于小说任务前必须验证通过。

### 8.4 切换失败引导

当以下场景因为模型未验证失败时：

- 首页或设置页更新默认模型。
- 创建任务选择模型后提交。
- 运行页或审核页选择动作模型后提交。

错误提示增加操作：

- `去 AI 对话验证`

跳转建议：

```text
/chat?model=K2.7&validate=1
```

`ChatClient` 读取 query 后：

- 预选 `K2.7`。
- 自动打开验证面板。
- 不自动发起验证，避免页面加载就消耗模型调用；用户点击 `运行验证`。

## 9. 错误处理

### 9.1 网关错误

展示：

- HTTP 状态或网关错误摘要。
- 当前协议。
- 建议检查 base URL、模型权限或协议覆盖。

### 9.2 推理信号缺失

展示：

- `未收到推理信号。`
- 说明：`该模型可能可用于普通聊天，但当前小说任务流要求可观测推理信号，因此不能自动标记为已验证。`

### 9.3 JSON 解析失败

展示：

- 解析错误摘要。
- 模型返回的前 200 字符预览，隐藏完整内容。
- 建议：`可重试；如果持续失败，需要为该模型增加专用 prompt 或暂不支持小说任务流。`

### 9.4 用户中断

如果用户取消验证：

- 不写入 `tasklog/model_compatibility.json`，模型目录保持原状态。
- 当前前端面板显示临时状态 `cancelled` 和说明 `用户取消验证`。
- 已产生的临时对话消息保留在当前会话中。

## 10. 数据流

```text
用户打开 /chat?model=K2.7&validate=1
  -> ChatClient 预选模型并打开验证面板
  -> 用户点击运行验证
  -> 前端 POST /api/model-validation/stream，body: {"model_id":"K2.7"}
  -> 后端 ModelCompatibilityService 逐项验证并 SSE 输出事件
  -> 前端更新检查项与聊天消息
  -> 验证通过后写入 tasklog/model_compatibility.json
  -> 前端刷新 /api/models?refresh=true
  -> K2.7 metadata.compatibility 变为 verified
  -> 设置默认模型或创建小说任务不再被兼容性门禁阻断
```

## 11. 测试范围

### 11.1 后端测试

- 验证服务能保存和读取 `tasklog/model_compatibility.json`。
- `verified` 覆盖能让网关模型变为 `compatibility=verified` 且 `novel_task_supported=true`。
- `failed` 覆盖不会放行小说任务流。
- 纯 registry 模型不能仅靠覆盖变成网关可用模型。
- SSE 验证事件按 `started -> check/chat_chunk -> done/error` 输出。
- 推理信号缺失、上下文哨兵缺失、JSON 解析失败分别产生明确失败原因。

### 11.2 前端测试

- 模型验证状态标签渲染正确。
- 验证面板能根据 SSE 事件更新每个检查项状态。
- 验证通过后触发模型目录刷新。
- 失败报告展示原因，不把失败模型误标为已验证。
- `/chat?model=K2.7&validate=1` 会预选模型并打开验证面板。
- 模型切换失败提示能生成正确验证入口链接。

### 11.3 手工验证

- 使用真实 `K2.7` 运行验证。
- 验证通过后在设置默认模型处选择 `K2.7`，不再出现“未完成兼容性验证”。
- 使用一个故意不支持 reasoning signal 的模型或 mock 网关，确认失败原因可读。

## 12. 风险与边界

- 不同 provider 对 `reasoning_content` 支持不同。首批按用户要求把推理信号作为硬门禁；如果后续希望普通强模型也能通过，可把该项降级为 warning，但本设计不默认放宽。
- 验证通过只代表“协议与最小任务流兼容”，不代表模型文学质量好。
- 验证会消耗真实模型调用，需要在 UI 上明确显示。
- 本地覆盖文件是单机状态，不适合多实例部署；当前项目本地开发形态可以接受。
