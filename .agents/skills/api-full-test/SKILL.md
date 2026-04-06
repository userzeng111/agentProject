---
name: api-full-test
description: Use when needing a comprehensive API endpoint smoke test after backend/frontend changes. Covers all API routes including health, models, dashboard, tasks CRUD, workspace, supervisor, review, result, chapters, artifacts, archive, chat, file-text, and default-model settings. Also tests SPA fallback routing for dynamic pages.
---

# 全量 API 接口自检 Skill

## 概述
对项目所有后端 API 端点进行全量冒烟测试，包括：
- 基础接口（health、models、dashboard）
- 任务 CRUD（创建、查询、运行、恢复）
- 任务详情（workspace、supervisor、review、result、chapters、artifacts）
- 归档（列表、详情）
- 聊天（流式 SSE、非流式 completions）
- 文件访问（file-text、tasks/{id}/files）
- 设置（default-model）
- SPA 路由回退（动态任务页面是否返回 index.html）

## 何时使用
- 修改了 `apps/agent-runtime/app/api/routes.py` 后
- 修改了 `apps/agent-runtime/app/main.py`（CORS、中间件、静态文件挂载）后
- 修改了 `apps/agent-runtime/app/application/task_service.py` 后
- 部署前后端联调验证
- 出现"接口 404/400/500""页面打不开""SPA 回退失效"等问题

## 使用方式
确保后端已启动（默认 `http://127.0.0.1:8000`），然后运行：

```bash
python3 .agents/skills/api-full-test/scripts/run_full_test.py
```

自定义后端地址：

```bash
python3 .agents/skills/api-full-test/scripts/run_full_test.py \
  --backend-url http://127.0.0.1:8000
```

## 测试覆盖

### 1. 基础接口
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/models` | GET | 模型列表 |
| `/api/dashboard` | GET | 首页聚合数据 |

### 2. 任务 CRUD
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/tasks` | POST | 创建任务 |
| `/api/tasks/{id}` | GET | 任务详情 |
| `/api/tasks/{id}/run` | POST | 启动任务 |
| `/api/tasks/{id}/resume` | POST | 恢复/审核任务 |
| `/api/tasks/{id}/assets` | POST | 上传素材 |

### 3. 任务详情
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/tasks/{id}/workspace` | GET | 工作台数据 |
| `/api/tasks/{id}/supervisor` | GET | Supervisor 计划 |
| `/api/tasks/{id}/review` | GET | 审核数据 |
| `/api/tasks/{id}/result` | GET | 结果数据 |
| `/api/tasks/{id}/chapters` | GET | 当前章节列表 |
| `/api/tasks/{id}/artifacts` | GET | 产物列表 |

### 4. 归档
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/archive` | GET | 归档列表（分页） |
| `/api/archive/{id}` | GET | 归档详情 |

### 5. 聊天
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat/stream` | POST | SSE 流式聊天 |
| `/api/chat/completions` | POST | OpenAI 兼容接口 |

### 6. 文件与设置
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/file-text` | GET | 读取文本引用 |
| `/api/tasks/{id}/files/{path}` | GET | 读取任务文件 |
| `/api/settings/default-model` | PATCH | 切换默认模型 |

### 7. SPA 路由回退
| 路径 | 预期 |
|------|------|
| `/tasks/{fake-id}/` | 200，返回 index.html |
| `/review/{fake-id}/` | 200，返回 index.html |
| `/result/{fake-id}/` | 200，返回 index.html |
| `/_next/static/css/*` | 200，返回静态资源 |

## 结果判断
- `[OK]` — 通过
- `[WARN]` — 警告（如 review/result 对未到阶段任务返回 400，属于预期行为）
- `[FAIL]` — 失败，需排查
- 最终输出通过/警告/失败统计

## 常见根因
- 接口 404：路由注册缺失或 APIRouter prefix 错误
- 接口 400：请求参数不匹配或任务状态不满足前置条件
- 接口 500：后端代码异常，查看 uvicorn 日志
- SPA 404：StaticFiles 挂载未配置 fallback，或 Cloudflare Pages 未配置 `_redirects`
- CORS 阻断：`main.py` 的 `allow_origins` 未包含请求来源
