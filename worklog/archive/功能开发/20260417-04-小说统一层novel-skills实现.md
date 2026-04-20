# 问题标题
小说统一层 novel_skills 实现

# 用户原始诉求
你负责新增 `app/novel_skills/**`，只改这个目录。不是唯一开发者，不要回退他人改动。目标：实现只服务小说的统一层，最少包含 workflow package 解析、style package 解析、runtime context 合并；满足测试 `tests/test_novel_skills.py` 的需求。完成后回复修改文件和要点。

# 当前状态
已完成：`app/novel_skills/**` 已实现并接入运行时主链路，满足测试与真实链路要求。

# 当前结论
- 本次范围被用户限定为仅修改 `app/novel_skills/**`。
- 目标是新增“只服务小说”的统一层，不做通用 Agent Skill 泛化。
- 至少需要覆盖三类能力：`workflow package` 解析、`style package` 解析、`runtime context` 合并。
- 需要以 `apps/agent-runtime/tests/test_novel_skills.py` 为最小验收面。
- 测试当前只覆盖两个能力点：
  - 从 `workflow_root/SKILL.md` 读取 front matter 与正文，生成 `kind=workflow` 的 package，并输出 `compiled_guidance`；
  - 在 `mode=style_remix` 时，把 workflow guidance 与 style guidance 合并到统一 runtime context，输出 `active_instance_id` 与 `active_package_ids`。
- 仓库内已有可复用实现：
  - `app/style_profiles/service.py` 已负责 `registry.yaml`、`manifest.yaml`、`rules/*.md` 的小说风格实例解析与 `compiled_summary` 编译；
  - `app/methodology/novel-writer-workflow/SKILL.md` 可作为默认 workflow package 源。
- 初步建议是新增 `NovelSkillService` 作为小说专用聚合层：
  - workflow 包由 `SKILL.md` 解析；
  - style 包通过复用 `StyleProfileService` 暴露统一 package 视图；
  - runtime context 负责按任务模式合并 guidance，避免重复发明 style 解析逻辑。

# 补充约束
- 已尝试按仓库规则使用 `context7` 查询 PyYAML 最新文档，但当前 MCP 配额已耗尽，无法返回库文档；后续实现需以仓库现有 `yaml.safe_load` / `yaml.safe_load_all` 用法为回退口径。
