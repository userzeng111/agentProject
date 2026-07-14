# UI/UX 大改造回滚指南

## 回滚原则

- 只反转前端入口映射并恢复上一个静态产物
- 不迁移或修改任务数据，后端任务可继续执行
- 回滚后异常率恢复正常即确认成功

## 回滚步骤

### 1. 恢复前端路由映射

将 `apps/web/src/lib/task-routes.ts` 恢复为旧版路由：

```bash
git checkout HEAD~1 -- apps/web/src/lib/task-routes.ts
```

关键变更：
- `projectViewHref()` 替换为 `reviewHref()` / `resultHref()` / `archiveDetailHref()`
- `workspaceHref()` 去掉尾斜杠
- 移除 `legacyProjectHref()` / `legacyCreateHref()`

### 2. 恢复旧页面入口

将重定向壳恢复为实际页面：

```bash
# 恢复各个被替换的页面
git checkout HEAD~1 -- apps/web/src/app/review/page.tsx
git checkout HEAD~1 -- apps/web/src/app/result/page.tsx
git checkout HEAD~1 -- apps/web/src/app/archive/detail/page.tsx
git checkout HEAD~1 -- apps/web/src/app/tasks/legacy-tasks-page.tsx
git checkout HEAD~1 -- apps/web/src/app/create/legacy-create-page.tsx
```

### 3. 恢复 feature client 旧路由逻辑

```bash
git checkout HEAD~1 -- apps/web/src/features/task-run/task-run-client.tsx
git checkout HEAD~1 -- apps/web/src/features/task-review/task-review-client.tsx
git checkout HEAD~1 -- apps/web/src/features/task-result/task-result-client.tsx
git checkout HEAD~1 -- apps/web/src/features/task-archive/archive-detail-client.tsx
git checkout HEAD~1 -- apps/web/src/features/task-archive/archive-list-client.tsx
git checkout HEAD~1 -- apps/web/src/features/task-dashboard/task-card-state.mjs
git checkout HEAD~1 -- apps/web/src/features/task-create/create-task-client.tsx
```

### 4. 移除新增组件

```bash
rm -rf apps/web/src/features/project/
git checkout HEAD~1 -- apps/web/src/app/p/[projectId]/page.tsx
```

### 5. 恢复 AppHeader

```bash
git checkout HEAD~1 -- apps/web/src/components/app-header.tsx
```

### 6. 构建并部署

```bash
cd apps/web && npm ci && npm run build
```

验证构建产物在 `out/` 目录完整。

### 7. 验证回滚

- 前端访问 `/` 首页正常
- 旧路由 `/tasks?id=xxx` 可直接访问工作台
- 旧路由 `/review?id=xxx` 可直接访问审核页
- 任务创建、审核提交、恢复、归档确认可正常操作
- 模型保存和刷新正常

## 观察指标

| 指标 | 预期 |
|------|------|
| 任务创建成功率 | >= 99% |
| 审核提交成功率 | >= 99% |
| 模型保存错误率 | < 1% |
| 404 错误率 | 恢复前水平 |

## 异常回退

若回滚后指标未恢复，再次确认步骤 1-5 是否完整执行：

```bash
# 检查当前 task-routes.ts 是否已恢复旧版
grep "reviewHref" apps/web/src/lib/task-routes.ts
# 应输出函数定义，而非缺失

# 检查 ProjectPageClient 是否已移除
ls apps/web/src/features/project/
# 应显示 "No such file or directory"
```
