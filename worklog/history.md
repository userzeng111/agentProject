# 历史问题索引

- 标题：任务历史持久化与工作台反馈设计
  路径：`worklog/archive/agent架构/20260331-01-任务历史持久化与工作台反馈设计.md`
  摘要：完成 tasklog 文件化持久化、聚合接口、SSE 工作台反馈与首页/审核/结果页映射。
- 标题：上下文管理器与缓存压缩规划
  路径：`worklog/archive/agent架构/20260331-02-上下文管理器与缓存压缩规划.md`
  摘要：完成上下文管理器、模型能力画像、上下文压缩与缓存状态前后端接入，并通过联调验证。
- 标题：上下文与缓存未实际生效复核
  路径：`worklog/archive/agent架构/20260331-03-上下文与缓存未实际生效复核.md`
  摘要：完成真实消息链上下文与持久化响应缓存修复，并验证缓存命中与消息历史已真实生效。
- 标题：聊天历史持久化与恢复
  路径：`worklog/archive/功能开发/20260406-01-聊天历史持久化与恢复.md`
  摘要：AI 对话页面已支持多会话 localStorage 持久化、切换恢复与删除历史会话。
- 标题：自动审核重写评分0分
  路径：`worklog/archive/功能开发/20260406-02-自动审核重写评分0分.md`
  摘要：自动审核 trace 已写入 overall_score 并累积历史，前端评分展示同步修正。
- 标题：流式输出与多轮对话实现
  路径：`worklog/archive/agent架构/20260404-01-流式输出与多轮对话实现.md`
  摘要：网关、后端聊天接口与前端聊天页均已支持流式输出和多轮对话。
- 标题：剩余未提交内容提交必要性分析
  路径：`worklog/archive/功能开发/20260421-01-剩余未提交内容提交必要性分析.md`
  摘要：完成当前未提交内容分类，确认 uv.lock 可单独补提，本地 RAG 数据与子项目继续保留本地。

- 标题：剩余 active 事项收敛执行规划
  路径：`worklog/archive/功能开发/20260421-02-剩余active事项收敛执行规划.md`
  摘要：完成当前 active 清单收敛，区分已完成可归档条目与仍需继续开发事项。
- 标题：8000 后端未更新导致 RAG 设置接口 405
  路径：`worklog/archive/功能开发/20260413-02-8000后端未更新导致RAG设置接口405.md`
  摘要：确认旧实例问题已消失，并在当前运行实例上实测 RAG 设置查询与全量重建接口返回 200。
- 标题：小说通用风格抽象边界对比设计
  路径：`worklog/archive/功能开发/20260417-03-小说通用风格抽象边界对比设计.md`
  摘要：提炼小说风格统一层的最小公共抽象，后续已由 style_profiles 与 novel_skills 运行时实现吸收。
- 标题：novel_skill_service 主链路最小接入建议
  路径：`worklog/archive/功能开发/20260417-04-novel-skill-service主链路最小接入建议.md`
  摘要：明确 workflow_guidance 与 style_guidance 主链路接入点，后续实现已验证生效。
- 标题：前端章节批次假设兼容性分析
  路径：`worklog/archive/功能开发/20260417-06-前端章节批次假设兼容性分析.md`
  摘要：完成章节批次展示假设梳理，相关前后端兼容改造已被后续实现吸收。
- 标题：固定两章一批实现与恢复逻辑分析
  路径：`worklog/archive/功能开发/20260417-06-固定两章一批实现与恢复逻辑分析.md`
  摘要：定位批次与恢复逻辑风险点，后续首批两章后续单章策略与恢复修复已落地。
- 标题：自动分配创建 Agent 功能设计
  路径：`worklog/archive/agent架构/20260407-01-自动分配创建agent功能设计.md`
  摘要：动态 Agent 编排能力已完成 API 级集成验证，包含 health、orchestrate 与 compare 路由测试。
- 标题：动态 Agent 替换旧硬编码审核
  路径：`worklog/archive/agent架构/20260407-02-动态agent替换旧硬编码审核.md`
  摘要：主图已接入动态审核桥接并补齐兜底逻辑，验证旧审核器不可用时仍可由动态桥接接管。
- 标题：normalized_spec 持久化写回时机分析
  路径：`worklog/archive/agent架构/20260417-01-normalized_spec持久化写回时机分析.md`
  摘要：运行前预写回方案已落地，并新增时序测试锁定 task.json 在 graph 返回前可见。
- 标题：运行时状态机阻塞只读排查 task_af31e4c58f
  路径：`worklog/archive/agent架构/20260417-02-运行时状态机阻塞只读排查-task-af31e4c58f.md`
  摘要：阻塞根因已被后续 review 同步与恢复链路修复吸收，问题单完成归档。
- 标题：后台线程异常与结果落盘链路排查
  路径：`worklog/archive/agent架构/20260417-03-后台线程异常与结果落盘链路排查.md`
  摘要：补齐 TaskService 稳态保护，避免 interrupt 或完成后被尾部异常覆盖为 failed，并通过回归验证。

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
