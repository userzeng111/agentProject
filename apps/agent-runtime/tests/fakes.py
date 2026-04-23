"""测试中共享的 Fake 类，减少各测试文件中的重复定义。"""

from typing import Any

from app.domain.models import ChapterDraft, ChapterPlan, StoryPlan


class FakePacket:
    def __init__(self, stage: str) -> None:
        self.stage = stage

    def model_dump(self, mode: str = "json") -> dict:
        return {"stage": self.stage, "mode": mode}


class FakeSnapshot:
    def __init__(self, stage: str) -> None:
        self.packet = FakePacket(stage)
        self.stage = stage

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "stage": self.stage,
            "mode": mode,
            "packet": self.packet.model_dump(mode=mode),
        }


class FakeContextManager:
    def build_snapshot(self, task_id, stage, instruction, model_profile, references, memory_items):
        return FakeSnapshot(stage)


class FakeGatewayClient:
    """通用假网关客户端，支持按顺序返回预设响应。"""

    def __init__(self, responses=None):
        self.responses = list(responses) if responses else []
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, messages, model=None):
        self.calls.append(
            {
                "messages": [dict(item) for item in messages],
                "model": model,
            }
        )
        return self.responses[len(self.calls) - 1]

    def list_models(self):
        return []


class FakeStoryEngine:
    """通用假 StoryEngine，覆盖主要生成/校验接口。"""

    def __init__(self) -> None:
        self.generated_batch_indexes: list[int] = []
        self.generated_batch_sizes: list[int] = []

    def build_story_plan(self, spec, reference_text, context_packet=None, model=None, revision_comment="", original_plan=None):
        return StoryPlan(
            working_title="夜半回廊",
            logline="测试梗概",
            world_notes=["世界观"],
            character_notes=["人物"],
            chapter_plan=[
                ChapterPlan(number=1, title="第1章", goal="目标1"),
                ChapterPlan(number=2, title="第2章", goal="目标2"),
                ChapterPlan(number=3, title="第3章", goal="目标3"),
                ChapterPlan(number=4, title="第4章", goal="目标4"),
                ChapterPlan(number=5, title="第5章", goal="目标5"),
            ],
        )

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
        self.generated_batch_indexes.append(batch_index)
        chapter_plan = story_plan.get("chapter_plan") or []
        if spec.get("mode") == "style_remix":
            batch_size = 2 if len(completed_chapters) == 0 else 1
        else:
            batch_size = 2
        self.generated_batch_sizes.append(batch_size)
        pair = []
        for chapter in chapter_plan[batch_index : batch_index + batch_size]:
            pair.append(
                ChapterDraft(
                    number=chapter["number"],
                    title=chapter["title"],
                    summary=f"{chapter['title']} 摘要",
                    content=f"{chapter['title']} 正文",
                )
            )
        return pair

    def revise_chapter_pair(
        self,
        current_pair,
        revision_comment,
        spec,
        story_plan,
        completed_chapters,
        reference_text,
        context_packet=None,
        model=None,
    ):
        return [ChapterDraft.model_validate(item) for item in current_pair]

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

    def fix_verified_issues(
        self,
        completed_chapters,
        verification_report,
        review_comment,
        story_plan,
        spec,
        reference_text,
        context_packet=None,
        model=None,
    ):
        return completed_chapters


class FakeRagService:
    """通用假 RAG 服务，用于 chat completions 测试。"""

    def __init__(self, hits=None, selected_contexts=None):
        self.hits = hits or []
        self.selected_contexts = selected_contexts or []

    def augment_chat_messages(self, messages, top_k=None):
        from app.rag.service import RagHit, RagSearchResult

        augmented = [
            {"role": "system", "content": "参考资料：" + self.selected_contexts[0]}
            if self.selected_contexts
            else {"role": "system", "content": ""},
            *messages,
        ]
        result = RagSearchResult(
            query="",
            hits=self.hits or [RagHit(doc_id="fake", content="", score=1.0, metadata={})],
            selected_contexts=self.selected_contexts,
            error=None,
        )
        return augmented, result
