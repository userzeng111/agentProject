---
name: project-interface-smoke
description: Use only when the user explicitly requests a focused AgentProject frontend/backend route smoke check after route, API, or port changes. Verifies health, models, dashboard, canonical project routes, and optional temporary task lifecycle. Use --read-only for a no-write diagnosis; never run automatically during hot startup.
---

# 项目接口冒烟检查

## 概述
这个 skill 用来检查当前仓库最常见的前后端联通问题，重点覆盖：
- 前端动态路由是否可访问
- 后端健康检查与基础任务接口是否可用
- 前后端默认端口是否一致

核心原则：先跑统一 smoke 检查，再决定是路由问题、接口问题，还是启动配置问题。

## 何时使用
- 修改了 `apps/web/src/app/**` 页面路由
- 修改了 `apps/agent-runtime/app/api/**` 接口
- 修改了 `apps/web/src/lib/api.ts`
- 修改了 `start.sh`、`README.md`、端口配置
- 出现“页面不存在”“点击查看打不开”“接口 404/400/500”这类问题

## 使用方式
1. 仅在用户明确要求检查时启动或使用已有的后端与前端服务；热启动时不要自动触发本检查。
2. 再运行：

```bash
python3 .agents/skills/project-interface-smoke/scripts/run_smoke.py
```

如果端口不是默认值，可显式传参：

```bash
python3 .agents/skills/project-interface-smoke/scripts/run_smoke.py \
  --frontend-url http://localhost:3000 \
  --backend-url http://localhost:8000
```

脚本只从当前 `/api/models` 中选择兼容性已验证的小说模型；需要指定模型时传入 `--model-id <模型 ID>`，不会使用默认或写死模型。

无可用模型、只需判断端口和路由时使用：

```bash
python3 .agents/skills/project-interface-smoke/scripts/run_smoke.py --read-only
```

默认会删除新建的测试任务；排查任务状态时才传入 `--keep-test-task`。页面检查使用当前规范路径 `/p/{task_id}/?view=...`，不依赖旧路由别名。

## 检查内容
- 后端：
  - `/api/health`
  - `/api/models`
  - `/api/dashboard`
  - `POST /api/tasks`
  - `/api/tasks/{id}`
  - `/api/tasks/{id}/workspace`
  - `/api/tasks/{id}/supervisor`
- 前端：
  - `/`
  - `/new/`
  - `/archive/`
  - `/chat/`
  - `/p/{id}/`
  - `/p/{id}/?view=review`
  - `/p/{id}/?view=result`
  - `/p/{id}/?view=archive`

## 常见根因
- Next.js 被配置成静态导出，但任务详情页依赖运行期动态 ID
- 静态站模式下仍使用 `/tasks/{id}` 这一类运行期动态路径
- `start.sh` 启动端口与前端默认 API 基地址不一致
- 动态详情页误用了 `force-static` 或占位参数

## 结果判断
- 只要任一页面返回 `404`，优先检查路由模式和构建输出模式。
- 只要基础 API 不通，优先检查后端端口和服务启动状态。
- 只要前端页面能开但数据失败，优先检查 `apps/web/src/lib/api.ts` 与后端接口契约。
