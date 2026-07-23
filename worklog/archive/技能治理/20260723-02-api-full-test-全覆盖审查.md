# api-full-test 全覆盖审查

## 用户原始诉求

对于 `api-full-test` 脚本，审查其固定代码能否成立“全覆盖”声明。

## 审查结论

原脚本是固定端点、固定 `created` 任务状态的关键链路冒烟检查，无法证明项目 API 全覆盖。`routes.py` 注册 46 个 v1 方法+路径，`dynamic_routes.py` 另注册 3 个 v2 方法+路径；原普通模式最多请求 18 个 v1 操作，且大量任务状态机、RAG、模型验证、设置、事件流、文件和动态编排接口缺失。

## 讨论结论

改用运行时 `/openapi.json` 发现接口，并在 skill 内保存项目专属 API 清单和声明式测试计划。新增、删除、契约变化或未分类接口均不能静默放行；默认仅测试当前改动映射的模块，显式全量时才运行全部模块。

## 实施结果

- 已将固定端点脚本重构为 OpenAPI 驱动执行器，新增 `check`、`sync`、`changed`、`full`、`read-only` 模式。默认 `changed` 只按 Git 改动或 `--changed-files` 映射到模块，并运行对应最小 pytest 目标；`full` 才运行全部已配置模块。
- 新增并固化 49 个 `/api/**` v1/v2 operation 的 `references/api-inventory.json`，指纹覆盖方法、路径、参数、请求体、响应、鉴权和弃用状态，忽略文档性字段并展开本地 schema 引用。
- 新增 `references/test-plan.json`（49/49 必测接口已分类）与 `references/module-impact-patterns.json`（13 个模块到已有 pytest 目标的映射）。新增、删除、契约变化、未分类、过期计划、重复计划或无 pytest 映射均为失败门禁。
- `sync` 虽会显式写入新 inventory，但只要发现新增、删除或契约变化仍以“清单待审查”失败退出，不能因同步动作自动接受覆盖。
- 真实网关请求只在显式 `--live-gateway --model-id` 时读取声明式 `live_request`；聊天 SSE 必须出现 chunk/done 且禁止 chat.error，避免 HTTP 200 错误帧误报通过。
- 已新增离线 eval，覆盖未分类阻断、sync 不修改测试计划且契约变更仍待审查、changed/full 选择范围、read-only 无状态机请求和 HTTP 200 的 chat.error SSE 拒绝。

## 验证结果

- `uv run --project apps/agent-runtime pytest apps/agent-runtime/tests/test_api_full_test_script.py -q`：6 passed。
- `ruff check`、`py_compile`、`git diff --check`、skill `quick_validate.py`：通过。
- 实例后端 `--mode check`：49 个操作一致、无未分类/过期/重复计划、模块映射完整。
- 实例后端 `--mode changed --changed-files .agents/skills/api-full-test/scripts/run_full_test.py`：仅 `api-gate` 模块，6 项 pytest 通过。
- 实例后端 `--mode read-only`：8 个安全 GET 探测通过；未触发写入或真实模型调用。

## 最终状态

已完成并归档。
