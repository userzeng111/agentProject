---
name: api-full-test
description: Use when the user asks to verify AgentProject APIs after a change or before release. Discover operations from the live OpenAPI document, compare them with the skill inventory, and execute declarative scenarios. The default changed mode tests only modules affected by the current code change; run --mode full only when the user explicitly requests all modules or a release gate. Never invoke automatically during hot startup.
---

# OpenAPI 增量接口自检 Skill

## 目标

本 Skill 的接口事实源是运行中后端的 `<backend-url>/openapi.json`，不是 Python 中手写的一张固定端点表。

- `references/api-inventory.json`：提交到仓库的 API 清单，保存方法、路径、`operationId`、契约摘要和 OpenAPI 语义指纹。
- `references/test-plan.json`：声明式测试计划，按 operation key 记录所属模块、测试层级、场景和必测标记；真实网关操作可额外声明请求、响应或 SSE 断言。
- `references/module-impact-patterns.json`：代码文件到模块、模块到既有 pytest 目标的映射。
- 通用执行器解释这些文件：先校验 OpenAPI/计划覆盖，再按影响映射调用最小 pytest 集合；真实网关请求只执行计划中声明的操作。新增接口或测试场景时，增量补充清单、计划和必要的 pytest 目标/映射，不重建整份 curl/Python 测试脚本，也不为特定路径增加分支。

OpenAPI 的 `description` 等文档性变更不构成接口变更；方法、路径、参数、请求体、响应、鉴权及弃用语义的变化才会进入差异集。

## 何时使用

- 用户要求验证本次后端/前端改动涉及的 API：使用默认 `changed` 模式。
- 用户要求审查接口清单漂移或准备补测试计划：使用 `check` 或 `sync`。
- 用户明确要求发布前、夜间或“全量模块/API 门禁”：使用 `full`。
- 用户要求无写入诊断：使用 `read-only`。

不要在服务热启动时自动调用，也不要因普通改动而自动扩大为全量测试。未指定全量时，只验证本次代码变更能够映射到的模块及其声明式流程依赖。

## 执行流程

每种模式先执行发现，再决定测试范围：

1. 拉取 live OpenAPI 并规范化 operation 指纹。
2. 与 `api-inventory.json` 双向比较，识别 `added`、`changed`、`removed`、`unchanged`。
3. 校验每个 inventory operation 都有 `test-plan.json` 分类和场景，并校验计划模块都有 `module-impact-patterns.json` 的 pytest 目标；新增、删除、契约变化或未分类 operation 均不能静默通过。
4. 根据模式选择模块，运行对应的确定性 pytest 目标；仅在显式开启真实网关时，执行计划中配置的请求、JSON 或 SSE 断言。

多接口状态机的测试逻辑保留在对应 pytest 目标中。若接口变更影响此类流程，应扩展该模块的 pytest 目标或影响映射，而不是在执行器中添加 URL 特判。

## 模式与命令

确保后端已启动（默认 `http://localhost:8000`）。默认模式为 `changed`：

```bash
python3 .agents/skills/api-full-test/scripts/run_full_test.py \
  --base-ref origin/main
```

`--mode` 可选值如下：

- `check`：只发现并严格校验 live OpenAPI、清单和测试计划的漂移；不更新清单。
- `sync`：显式同步 API 清单候选项，供审查后提交；同步不等于自动接受覆盖。
- `changed`：默认模式。只运行本次变更文件在影响映射中命中的模块及其 pytest 目标。
- `full`：发现检查通过后运行所有已配置模块的确定性 pytest 目标。仅限用户明确要求全量模块测试或发布门禁时使用；默认仍不调用真实模型/聊天网关。
- `read-only`：不创建、修改或删除业务数据，不调用真实模型网关；只执行计划中允许的安全读取检查。

显式传入当前修改文件可避免依赖 Git 差异推导，参数可重复：

```bash
python3 .agents/skills/api-full-test/scripts/run_full_test.py \
  --mode changed \
  --changed-files apps/agent-runtime/app/api/routes.py \
  --changed-files apps/web/src/lib/api.ts
```

由 Git 基线推导改动范围：

```bash
python3 .agents/skills/api-full-test/scripts/run_full_test.py \
  --mode changed \
  --base-ref origin/main
```

仅检查 OpenAPI/清单/计划是否一致：

```bash
python3 .agents/skills/api-full-test/scripts/run_full_test.py --mode check
```

显式生成待审查的清单更新：

```bash
python3 .agents/skills/api-full-test/scripts/run_full_test.py --mode sync
```

用户明确要求全量模块测试时：

```bash
python3 .agents/skills/api-full-test/scripts/run_full_test.py \
  --mode full \
  --backend-url http://localhost:8000 \
  --frontend-url http://localhost:3000
```

用户还明确要求真实模型/聊天网关验收时，才额外开启网关调用：

```bash
python3 .agents/skills/api-full-test/scripts/run_full_test.py \
  --mode full \
  --live-gateway \
  --model-id <模型_ID> \
  --allow-gateway-unavailable
```

`--live-gateway` 默认关闭，即使 `full` 也只运行本地确定性场景。它是 token 成本和外部副作用的显式门禁；只有用户明确要求真实网关验证时才可传入。若同时传入 `--allow-gateway-unavailable`，仅允许将已识别的上游网关不可用降级为警告，不能跳过其他失败。

无写入诊断：

```bash
python3 .agents/skills/api-full-test/scripts/run_full_test.py \
  --mode read-only \
  --backend-url http://localhost:8000
```

## 通用参数

- `--changed-files <路径>`：可重复传入；声明本次要映射到模块和 pytest 目标的代码文件。
- `--base-ref <Git 引用>`：计算本次改动文件时使用的基线；未使用 `--changed-files` 时传入。
- `--backend-url <URL>`：后端地址，默认 `http://localhost:8000`。
- `--frontend-url <URL>`：前端 Origin；传入时执行 CORS 预检。
- `--timeout <秒>`：单次请求超时。
- `--model-id <模型 ID>`：计划中的实时网关请求需要模型变量时传入。
- `--live-gateway`：显式允许所选场景调用真实模型/聊天网关；默认关闭，包括 `full` 模式。
- `--allow-gateway-unavailable`：只在已传入 `--live-gateway` 时生效，允许将明确的上游模型网关不可用降为警告，不能掩盖 API 漂移、计划缺失或本地契约失败；发布门禁不得使用。

## 覆盖与结果规则

“全量”仅指由当次 live OpenAPI、已声明计划和影响映射共同确定的全部模块测试目标，不是文档中的静态路径清单。`full` 会运行所有已配置模块的确定性 pytest；`changed` 只运行本次改动命中的模块测试目标。

- `[OK]`：发现检查和场景断言通过。
- `[WARN]`：只允许同时显式 `--live-gateway --allow-gateway-unavailable` 时的受控上游网关不可用等已声明降级。
- `[FAIL]`：OpenAPI 与 inventory 漂移、operation 未分类/无计划、模块映射/pytest 失败或未允许的网关失败。

新增 API 绝不会因执行 `sync` 自动视为已测试：必须为其补齐声明式计划和适当的场景，再通过 `check` 或所选测试模式。这样 API 发现、清单审查和测试覆盖形成可追溯闭环。
