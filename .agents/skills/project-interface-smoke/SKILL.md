---
name: project-interface-smoke
description: Use when checking this repository's web routes and API endpoints after frontend or backend changes, especially when task pages, review pages, result pages, archive pages, or local startup ports may be broken.
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
1. 先启动后端与前端开发服务。
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
  - `/create`
  - `/archive`
  - `/chat`
  - `/tasks/?id={id}`
  - `/review/?id={id}`
  - `/result/?id={id}`
  - `/archive/detail/?id={id}`

## 常见根因
- Next.js 被配置成静态导出，但任务详情页依赖运行期动态 ID
- 静态站模式下仍使用 `/tasks/{id}` 这一类运行期动态路径
- `start.sh` 启动端口与前端默认 API 基地址不一致
- 动态详情页误用了 `force-static` 或占位参数

## 结果判断
- 只要任一页面返回 `404`，优先检查路由模式和构建输出模式。
- 只要基础 API 不通，优先检查后端端口和服务启动状态。
- 只要前端页面能开但数据失败，优先检查 `apps/web/src/lib/api.ts` 与后端接口契约。
