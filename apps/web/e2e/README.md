# Playwright E2E 自动化测试

本目录覆盖 AgentProject 的浏览器级自动化测试流程。

## 运行命令

```bash
npm --prefix apps/web run test:e2e -- --project=chromium
npm --prefix apps/web run test:e2e:trace -- --project=chromium
```

首次运行如果缺少浏览器：

```bash
npm --prefix apps/web exec playwright install chromium
```

## 覆盖分层

- API 基线：轻量 API、CORS、本地任务创建与清理。
- 真实后端页面：主要页面可达、任务工作台、调试中心回归。
- 真实浏览器生命周期：创建页填表、上传 UTF-8 参考文本、进入工作台、通过 UI 删除任务并确认后端清理。
- Fixture UI 分支：难以低成本构造的任务状态、审核、结果、归档、聊天、设置分支。
- 慢测：真实 LLM/RAG 生成链路不进入默认 E2E，需要单独命令或手动任务验证。

## 注意

- 默认 E2E 会创建少量 `created` / `sources_ingested` 测试任务并尽力清理。
- Playwright 启动后端时会设置 `RATE_LIMIT_GENERAL_PER_MINUTE=1000` 与 `RATE_LIMIT_CHAT_PER_MINUTE=200`，避免完整套件的页面轮询和清理请求误触发本地限流。
- 测试不应断言或输出 prompt、raw response、章节正文、RAG 命中文本等敏感正文。
- 失败时产物位于 `apps/web/test-results/` 与 `apps/web/playwright-report/`。
