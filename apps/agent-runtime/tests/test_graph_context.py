import unittest

from langgraph.types import Command

from app.context.manager import ContextManager
from app.context.models import ReferenceMaterial
from app.domain.models import ChapterDraft, ChapterPlan, StoryPlan
from app.graph.main_graph import build_default_callbacks, build_graph
from app.graph.utils.helpers import _resolve_model_profile
from app.rag.service import RagHit, RagSearchResult
from tests.fakes import FakeVerifiedGatewayModelCatalog


class FakeEngine:
    def __init__(self) -> None:
        self.gateway_client = None
        self.outline_contexts = []
        self.chapter_pair_contexts = []

    def build_story_plan(self, spec, reference_text, context_packet=None, model=None):
        self.outline_contexts.append(context_packet)
        return StoryPlan(
            working_title="测试标题",
            logline="测试梗概",
            world_notes=["世界观"],
            character_notes=["人物"],
            chapter_plan=[ChapterPlan(number=1, title="第一章", goal="建立冲突")],
        )

    def build_chapter_plan_batch(self, spec, story_plan, batch_index, batch_size, confirmed_chapter_plans, model=None):
        chapter_plan = story_plan.get("chapter_plan") or []
        return [
            ChapterPlan(number=ch["number"], title=ch["title"], goal=ch["goal"])
            for ch in chapter_plan[batch_index : batch_index + batch_size]
        ]

    def generate_chapter_pair(
        self,
        spec,
        story_plan,
        batch_index,
        completed_chapters,
        reference_text,
        context_packet=None,
        model=None,
        progress_callback=None,
    ):
        self.chapter_pair_contexts.append(context_packet)
        return [
            ChapterDraft(
                number=1,
                title="第一章",
                summary="建立冲突",
                content="测试正文",
            )
        ]

    def verify_full_story(
        self,
        completed_chapters,
        story_plan,
        spec,
        reference_text,
        context_packet=None,
        model=None,
    ):
        return {"overall_score": 100, "issues": []}


class FakeRagService:
    def search_for_story_outline(self, *, spec):
        return RagSearchResult(
            query=spec.get("prompt", ""),
            hits=[RagHit(doc_id="rag-1", content="灯塔档案：夜航记录曾被篡改。", score=0.93, metadata={})],
            selected_contexts=["灯塔档案：夜航记录曾被篡改。"],
            error=None,
        )

    def search_for_story_chapter(self, *, spec, story_plan, batch_index, completed_chapters):
        return RagSearchResult(
            query=story_plan.get("working_title", ""),
            hits=[RagHit(doc_id="rag-2", content="港口潮汐表：凌晨两点会出现异常回流。", score=0.88, metadata={})],
            selected_contexts=["港口潮汐表：凌晨两点会出现异常回流。"],
            error=None,
            selected_hits=[RagHit(doc_id="rag-2", content="港口潮汐表：凌晨两点会出现异常回流。", score=0.88, metadata={})],
        )

    def build_reference_materials(self, result, *, prefix, start_priority=40):
        return [
            ReferenceMaterial(
                source_id=f"{prefix}-1",
                title=f"{prefix}资料",
                content=result.selected_contexts[0],
                priority=start_priority,
            )
        ]


class FakeVerifiedGatewayModelCatalogTests(unittest.TestCase):
    def test_missing_model_has_unknown_context_capabilities(self) -> None:
        profile = FakeVerifiedGatewayModelCatalog(("gpt-5.4",)).get_model_profile("not-in-gateway")

        self.assertEqual(profile["metadata"]["source"], "missing")
        self.assertEqual(profile["metadata"]["compatibility"], "unverified")
        self.assertEqual(profile["capabilities"]["context_window"], {})
        self.assertEqual(profile["capabilities"]["cache"], {})
        self.assertFalse(profile["capabilities"]["features"]["novel_task_supported"])

    def test_missing_model_is_rejected_before_context_building(self) -> None:
        catalog = FakeVerifiedGatewayModelCatalog(("gpt-5.4",))

        with self.assertRaisesRegex(ValueError, "不在当前供应商模型目录中"):
            _resolve_model_profile(catalog, "not-in-gateway")


class GraphContextIntegrationTests(unittest.TestCase):
    def test_graph_builds_outline_and_chapter_pair_context_snapshots(self) -> None:
        engine = FakeEngine()
        callbacks = build_default_callbacks(
            engine,
            context_manager=ContextManager(),
            model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
        )
        graph = build_graph(callbacks=callbacks)
        config = {"configurable": {"thread_id": "task-graph-1"}}
        initial_state = {
            "task_id": "task-graph-1",
            "input_payload": {
                "mode": "short_story",
                "prompt": "写一篇临海城市的悬疑故事",
                "genre": "悬疑",
                "style": "冷静克制",
                "target_words": 1800,
                "audience": "",
                "banned": "",
                "title_hint": "潮汐谜案",
                "model_id": "gpt-5.4",
            },
            "reference_text": "港口、潮水、旧案卷宗。",
        }

        first_result = graph.invoke(initial_state, config=config)

        self.assertIn("__interrupt__", first_result)
        first_snapshot = graph.get_state(config).values
        self.assertIn("outline_context_snapshot", first_snapshot)
        self.assertTrue(engine.outline_contexts)
        self.assertIsNotNone(engine.outline_contexts[0])

        # 总纲审核通过
        graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        # 章节计划批次审核通过
        graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)

        final_snapshot = graph.get_state(config).values
        self.assertIn("chapter_pair_context_packet", final_snapshot)
        self.assertTrue(engine.chapter_pair_contexts)
        self.assertIsNotNone(engine.chapter_pair_contexts[0])

    def test_graph_injects_rag_context_into_outline_and_chapter_snapshots(self) -> None:
        engine = FakeEngine()
        callbacks = build_default_callbacks(
            engine,
            context_manager=ContextManager(),
            model_catalog=FakeVerifiedGatewayModelCatalog(("gpt-5.4",)),
            rag_service=FakeRagService(),
        )
        graph = build_graph(callbacks=callbacks)
        config = {"configurable": {"thread_id": "task-graph-rag-1"}}
        initial_state = {
            "task_id": "task-graph-rag-1",
            "input_payload": {
                "mode": "short_story",
                "prompt": "写一篇临海城市的悬疑故事",
                "genre": "悬疑",
                "style": "冷静克制",
                "target_words": 1800,
                "audience": "",
                "banned": "",
                "title_hint": "潮汐谜案",
                "model_id": "gpt-5.4",
            },
            "reference_text": "港口、潮水、旧案卷宗。",
        }

        graph.invoke(initial_state, config=config)
        self.assertIn("灯塔档案", engine.outline_contexts[0]["references_text"])

        # 总纲审核通过
        graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        # 章节计划批次审核通过
        graph.invoke(Command(resume={"approved": True, "comment": "继续"}), config=config)
        self.assertIn("港口潮汐表", engine.chapter_pair_contexts[0]["references_text"])


if __name__ == "__main__":
    unittest.main()
