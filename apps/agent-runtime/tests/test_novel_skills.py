import tempfile
import unittest
from pathlib import Path


class NovelSkillServiceTests(unittest.TestCase):
    def test_loads_workflow_skill_package_from_skill_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workflow_root = root / "novel-workflow"
            workflow_root.mkdir(parents=True, exist_ok=True)
            (workflow_root / "SKILL.md").write_text(
                """---
name: novel-writer-workflow-guide
description: "用于小说方法论"
allowed-tools: Read, Grep
---

# Novel Writer 工作流

## 七步方法论

1. /constitution
2. /specify
3. /write
""",
                encoding="utf-8",
            )

            from app.novel_skills.service import NovelSkillService

            service = NovelSkillService(workflow_root=workflow_root, style_root=root / "missing-style")
            workflow = service.get_workflow_package()

            self.assertIsNotNone(workflow)
            assert workflow is not None
            self.assertEqual(workflow["kind"], "workflow")
            self.assertEqual(workflow["manifest"]["name"], "novel-writer-workflow-guide")
            self.assertIn("/constitution", workflow["compiled_guidance"])

    def test_build_runtime_context_merges_workflow_and_style_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workflow_root = root / "novel-workflow"
            workflow_root.mkdir(parents=True, exist_ok=True)
            (workflow_root / "SKILL.md").write_text(
                """---
name: novel-writer-workflow-guide
description: "用于小说方法论"
---

# Novel Writer 工作流

## 七步方法论

1. /constitution
2. /specify
3. /write
""",
                encoding="utf-8",
            )

            style_root = root / "bisheng-style"
            rules_root = style_root / "instances" / "douluo" / "rules"
            rules_root.mkdir(parents=True, exist_ok=True)
            (style_root / "SKILL.md").write_text(
                """---
name: bisheng-style
description: "用于小说风格实例"
---

# 笔生
""",
                encoding="utf-8",
            )
            (style_root / "instances" / "registry.yaml").write_text(
                """
instances:
  - instance_id: douluo
    name: "唐家三少风格实例"
    source_novel: "斗罗大陆"
    source_author: "唐家三少"
    genre: "玄幻"
    path: "instances/douluo/"
    status: active
    fidelity_score: 90
    description: "术语流"
                """.strip(),
                encoding="utf-8",
            )
            (style_root / "instances" / "douluo" / "manifest.yaml").write_text(
                'name: "唐家三少风格实例"\nsource_novel: "斗罗大陆"\nsource_author: "唐家三少"\n',
                encoding="utf-8",
            )
            (rules_root / "language.md").write_text("# 语言\n术语密集\n", encoding="utf-8")

            from app.novel_skills.service import NovelSkillService

            service = NovelSkillService(workflow_root=workflow_root, style_root=style_root)
            context = service.build_runtime_context(
                mode="style_remix",
                style_profile_id="douluo",
                custom_style="保留热血成长感",
            )

            self.assertIn("/constitution", context["workflow_guidance"])
            self.assertIn("唐家三少风格实例", context["style_guidance"])
            self.assertIn("保留热血成长感", context["style_guidance"])
            self.assertEqual(context["active_instance_id"], "douluo")
            self.assertEqual(context["active_package_ids"], ["novel-writer-workflow-guide", "bisheng-style"])
