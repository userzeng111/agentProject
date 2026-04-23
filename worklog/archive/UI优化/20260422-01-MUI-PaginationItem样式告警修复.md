# 问题标题
MUI PaginationItem 样式告警修复

# 用户原始诉求
- 自测试中前端开发服务持续输出 `MuiPaginationItem` 的样式覆盖告警。
- 需要继续修复该告警，避免前端调试输出持续污染并消除潜在样式覆盖风险。

# 当前状态
已完成修复并验证，待用户确认是否收口归档。

# 初步关注点
- 告警是否稳定复现于 `npm run dev` 访问页面后。
- 主题配置中是否只有 `MuiPaginationItem` 这一处仍在使用旧的 `selected` 状态写法。
- 修复后是否会影响分页选中态外观。

# 本轮结论
- 根因已确认：`apps/web/src/components/app-theme-provider.tsx` 中 `MuiPaginationItem.styleOverrides.selected` 使用了 MUI 已不推荐的状态覆盖写法，触发开发模式持续告警。
- 已将选中态样式改为 `root -> &.Mui-selected`，视觉参数保持不变，仅修正状态类覆盖方式。
- 代码库内与该告警直接相关的主题配置仅此一处。

# 验证
- 告警复现：
  - 启动 `npm run dev`
  - 访问 `/` 与 `/review/?id=task_0e057d3521`
  - 修复前可稳定看到 `MuiPaginationItem` 状态类特异性告警
- 修复后复验：
  - 启动 `npm run dev`
  - 再次访问 `/` 与 `/review/?id=task_0e057d3521`
  - 告警未再出现
- 生产构建：
  - `npm run build`
  - 结果：通过
