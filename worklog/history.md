# 历史问题索引

- 标题：waiting_manual_action 恢复原因前端展示缺失排查
  路径：`worklog/archive/agent架构/20260420-02-waiting_manual_action恢复原因前端展示缺失排查.md`
  摘要：补齐 waiting_manual_action 页面上的恢复原因展示，包含自然语言说明和结构化阻塞原因。
- 标题：旧异常任务恢复与清理机制设计
  路径：`worklog/archive/功能开发/20260420-01-旧异常任务恢复与清理机制设计.md`
  摘要：为历史异常任务实现自动恢复与手动恢复双轨机制，并验证旧任务可原地继续。
- 标题：真实长篇任务停留 planning 阻塞排查
  路径：`worklog/archive/功能开发/20260417-06-真实长篇任务停留planning阻塞排查.md`
  摘要：修复真实长篇任务卡在 planning 的阻塞，并完成多条正式长篇任务全链路复验。
- 标题：长篇小说分阶段续写批次调整
  路径：`worklog/archive/功能开发/20260417-05-长篇小说分阶段续写批次调整.md`
  摘要：将长篇 style_remix 批次策略调整为首批两章、后续单章，并经真实长篇任务验证。
- 标题：小说统一层 novel_skills 实现
  路径：`worklog/archive/功能开发/20260417-04-小说统一层novel-skills实现.md`
  摘要：实现小说专用 unified skill 层，统一 workflow 与 style 运行时上下文装配。
- 标题：通用 skill 调用兼容模块设计
  路径：`worklog/archive/功能开发/20260417-02-通用skill调用兼容模块设计.md`
  摘要：落地小说专用 skill 通用层设计，统一 workflow 与 style 两类包的接入路线。
- 标题：小说风格 skill 整合分析与接入设计
  路径：`worklog/archive/功能开发/20260417-01-小说风格skill整合分析与接入设计.md`
  摘要：完成 bisheng-style 到主项目风格复写链路的整合，并通过真实模型链路验证。
- 标题：小说 RAG 全链路测试
  路径：`worklog/archive/功能开发/20260413-01-小说RAG全链路测试.md`
  摘要：完成前后端冒烟、全量 API 自检以及真实小说 RAG 建库和问答验证，确认全链路可用。
- 标题：小说 RAG 语料库隔离与设置同步入口
  路径：`worklog/archive/功能开发/20260411-02-小说RAG语料库隔离与设置同步入口.md`
  摘要：为小说项目建立独立 RAG 数据库，新增设置页全量重建入口，并将建库模式与创作检索模式分离。
- 标题：AgentProject 接入 embeddingProject 实现小说 RAG
  路径：`worklog/archive/功能开发/20260411-01-AgentProject接入embeddingProject实现小说RAG.md`
  摘要：在主项目中新增统一 RAG 适配层，接入小说任务流与聊天问答，并通过后端全量测试验证。
- 标题：首页布局优化与分页设计
  路径：`worklog/archive/UI优化/20260401-01-首页布局优化与分页设计.md`
  摘要：首页双栏布局 + Tab 分组 + 紧凑卡片 + 前端分页，归档列表后端分页，参考知乎网页端设计。
- 标题：web动态路由修复与接口自检skill
  路径：`worklog/archive/agent架构/20260406-01-web动态路由修复与接口自检skill.md`
  摘要：修复网页端待处理任务查看跳转失败问题，补做接口自检，并将检查流程沉淀为测试 skill。
- 标题：前后端端口分离与cloudflare配置回切
  路径：`worklog/archive/agent架构/20260406-02-前后端端口分离与cloudflare配置回切.md`
  摘要：将项目默认口径调整为后端8000前端3000，并同步 Cloudflare tunnel 与自检配置。
