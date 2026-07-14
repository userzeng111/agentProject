# UI/UX 大改造验收清单

## 构建与部署验收

- [ ] `cd apps/web && npm ci && npm run build` 无错误
- [ ] `out/` 目录包含所有 13 个页面（含 `/p/__placeholder__/`）
- [ ] `out/_redirects` 包含 `/* /index.html 200`
- [ ] FastAPI SPA fallback 正确返回项目页静态壳

## 路由验收

### 新规范路由
- [ ] `/` → 作品库首页
- [ ] `/new/` → 创建页
- [ ] `/p/{id}/` → 项目工作台
- [ ] `/p/{id}/?view=review` → 审核页
- [ ] `/p/{id}/?view=result` → 结果页
- [ ] `/p/{id}/?view=archive` → 归档详情
- [ ] `/archive/` → 归档作品库
- [ ] `/chat/` → AI 对话
- [ ] `/settings/` → 设置页

### 旧路由兼容
- [ ] `/create?retry_from=X` → 跳转到 `/new/?retry_from=X`
- [ ] `/tasks?id=X` → 跳转到 `/p/X/`
- [ ] `/review?id=X` → 跳转到 `/p/X/?view=review`
- [ ] `/result?id=X` → 跳转到 `/p/X/?view=result`
- [ ] `/archive/detail?id=X` → 跳转到 `/p/X/?view=archive`
- [ ] `/archive/detail?id=X&tab=overview` → 跳转到 `/p/X/?view=archive&tab=overview`
- [ ] `/archive/detail?id=X&tab=read` → 跳转到 `/p/X/?view=archive&tab=read`
- [ ] 非法 `?view=xxx` → 显示"项目视图不存在"
- [ ] 非法 `?tab=xxx` → 规范化为 `overview`

## 功能验收

### 创建
- [ ] 填写表单 → 选择模型 → 提交 → 进入项目工作台
- [ ] RAG 未构建时显示警告
- [ ] 模型不可选时显示禁用原因
- [ ] 提交按钮禁用时 Tooltip 显示阻断原因

### 工作台
- [ ] 任务状态映射到五阶段导航
- [ ] activeor 按状态显示可用动作（开始创作/继续创作/进入审核/查看结果）
- [ ] 禁用按钮显示 Tooltip 原因
- [ ] 取消/删除操作有确认弹窗
- [ ] 工作流图谱默认折叠，可展开

### 审核
- [ ] 大纲审核：左侧大纲材料 + 右侧 Agent 追踪和决策
- [ ] 章节审核：左右分屏
- [ ] 验证审核：左右分屏

### 结果
- [ ] 阅读器可用，章节翻页
- [ ] 复制全文/导出 MD
- [ ] 确认归档

### 归档
- [ ] 归档详情展示概览/大纲/阅读/原始信息四页签
- [ ] Tab query 刷新后恢复

### 聊天
- [ ] 会话侧栏可新建/切换/删除会话
- [ ] 流式消息展示，思考过程可折叠
- [ ] 验证面板可打开

### 设置
- [ ] 模型协议表格在移动端显示为卡片列表
- [ ] 协议修改可保存

## 键盘验收

- [ ] Tab 可遍历首页导航
- [ ] Tab 可遍历创建页所有表单字段
- [ ] Tab 可遍历工作台所有动作
- [ ] Enter 可触发按钮动作
- [ ] 折叠控件 Tab 可达 + Enter/Space 展开
- [ ] Dialog Escape 可关闭

## 布局矩阵

- [ ] 320x740 无横向滚动
- [ ] 390x844 无横向滚动
- [ ] 768x1024 无横向滚动
- [ ] 1280x800 无横向滚动

## 回滚确认

回滚步骤见 `docs/superpowers/plans/2026-07-13-uiux-rollback-guide.md`。
