from app.domain.models import StoryPlan
from app.graph.nodes.outline import plan_story
from app.graph.routers.review import route_after_outline_review
from app.graph.state import OUTLINE_CHUNK_SIZE


class _OutlineEngine:
    supports_deferred_chapter_plan = True

    def build_story_plan(self, *_args, defer_chapter_plan=False, **_kwargs):
        plan = StoryPlan(
            working_title="窗口测试",
            logline="测试长篇分批规划。",
            planned_chapter_count=49,
            chapter_plan=[
                {"number": number, "title": f"第{number}章", "goal": "推进剧情"}
                for number in range(1, 50)
            ],
        )
        if defer_chapter_plan:
            plan.chapter_plan = []
        return plan


def test_master_outline_defers_full_chapter_plan() -> None:
    result = plan_story(
        {"normalized_spec": {"model_id": "test-model"}},
        engine=_OutlineEngine(),
    )

    assert result["outline_windowed"] is True
    assert result["outline_batch_size"] == OUTLINE_CHUNK_SIZE
    assert result["story_plan"]["chapter_plan"] == []


def test_windowed_outline_routes_after_each_five_but_stops_after_twenty() -> None:
    base = {
        "approved": True,
        "outline_phase": "chapter_batches",
        "outline_total_count": 49,
        "outline_windowed": True,
    }

    assert route_after_outline_review({**base, "outline_completed_count": 5}) == "plan_chapter_batch"
    assert route_after_outline_review({**base, "outline_completed_count": 20}) == "wait_for_window_drafts"
    assert route_after_outline_review({**base, "outline_completed_count": 40}) == "wait_for_window_drafts"
    assert route_after_outline_review({**base, "outline_completed_count": 49}) == "wait_for_window_drafts"


def test_legacy_full_outline_keeps_existing_route() -> None:
    assert route_after_outline_review(
        {
            "approved": True,
            "outline_phase": "chapter_batches",
            "outline_total_count": 49,
            "outline_completed_count": 49,
        }
    ) == "prepare_chapter_pair_context"
