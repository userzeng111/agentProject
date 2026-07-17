from __future__ import annotations

import pytest
from langgraph.errors import GraphInterrupt

from app.domain.models import StoryPlan
from app.graph.main_graph import _instrument_workflow_callback
from app.graph.nodes.final import assemble_result
from app.graph.nodes.outline import plan_story, review_outline
from app.graph.nodes.verification import fix_verified_issues, verify_full_story
from app.llm.story_engine import reset_progress_callback, set_progress_callback


class _MissingChapterCountEngine:
    def build_story_plan(self, *_args, **_kwargs) -> StoryPlan:
        return StoryPlan(
            working_title="缺少章节数",
            logline="测试大纲缺少章节数。",
            world_notes=["测试世界观"],
            character_notes=["测试人物"],
        )


def _normalized_spec() -> dict:
    return {"mode": "short_story", "model_id": "gpt-5.4"}


def test_missing_chapter_count_cannot_enter_followup_workflow() -> None:
    with pytest.raises(ValueError, match="缺少有效章节总数"):
        plan_story(
            {
                "normalized_spec": _normalized_spec(),
                "outline_context_packet": {},
                "reference_text": "",
            },
            engine=_MissingChapterCountEngine(),
        )


@pytest.mark.parametrize(
    "state, expected_message",
    [
        (
            {
                "completed_chapters": [],
                "story_plan": {"planned_chapter_count": 1, "chapter_plan": [{"number": 1}]},
                "normalized_spec": _normalized_spec(),
            },
            "尚未生成任何正文",
        ),
        (
            {
                "completed_chapters": [],
                "story_plan": {"planned_chapter_count": 1, "chapter_plan": [{"number": 1}]},
                "normalized_spec": _normalized_spec(),
            },
            "没有可修复的正文",
        ),
    ],
)
def test_empty_body_cannot_enter_verification_or_repair(state: dict, expected_message: str) -> None:
    operation = fix_verified_issues if "修复" in expected_message else verify_full_story
    with pytest.raises(ValueError, match=expected_message):
        operation(state, engine=object())


def test_assemble_result_rejects_empty_or_noncontinuous_chapters() -> None:
    base_state = {
        "story_plan": {
            "planned_chapter_count": 2,
            "chapter_plan": [{"number": 1}, {"number": 2}],
        },
        "normalized_spec": _normalized_spec(),
    }
    with pytest.raises(ValueError, match="正文数量不足"):
        assemble_result({**base_state, "completed_chapters": [{"number": 1, "content": "正文"}]})
    with pytest.raises(ValueError, match="编号不连续"):
        assemble_result(
            {
                **base_state,
                "completed_chapters": [
                    {"number": 1, "content": "正文"},
                    {"number": 3, "content": "正文"},
                ],
            }
        )


def test_manual_chapter_plan_approval_merges_confirmed_batch() -> None:
    state = {
        "task_id": "task-manual-outline-batch",
        "auto_review": False,
        "story_plan": {
            "working_title": "测试大纲",
            "logline": "测试梗概",
            "world_notes": ["测试世界观"],
            "character_notes": ["测试人物"],
            "planned_chapter_count": 2,
            "chapter_plan": [],
        },
        "outline_phase": "chapter_batches",
        "outline_batch_index": 0,
        "outline_batch_size": 20,
        "outline_total_count": 2,
        "current_batch_chapter_plans": [
            {"number": 1, "title": "第一章", "goal": "开始"},
            {"number": 2, "title": "第二章", "goal": "推进"},
        ],
    }
    result = review_outline(
        state,
        interrupt_outline_review=lambda *_args, **_kwargs: {"approved": True, "comment": "通过"},
    )

    assert result["outline_completed_count"] == 2
    assert [item["number"] for item in result["story_plan"]["chapter_plan"]] == [1, 2]


def test_workflow_node_events_cover_start_complete_and_failure() -> None:
    events: list[dict] = []
    token = set_progress_callback(events.append)
    try:
        _instrument_workflow_callback("plan_story", lambda _state: {"ok": True})({})
        with pytest.raises(RuntimeError, match="节点失败"):
            _instrument_workflow_callback(
                "review_outline",
                lambda _state: (_ for _ in ()).throw(RuntimeError("节点失败")),
            )({})
    finally:
        reset_progress_callback(token)

    assert [item["event_type"] for item in events] == [
        "workflow.node.started",
        "workflow.node.completed",
        "workflow.node.started",
        "workflow.node.failed",
    ]
    assert events[0]["stage"] == "planning"
    assert events[-1]["payload"]["error_type"] == "RuntimeError"


def test_workflow_node_interrupt_is_recorded_as_pause_not_failure() -> None:
    events: list[dict] = []
    token = set_progress_callback(events.append)
    try:
        with pytest.raises(GraphInterrupt):
            _instrument_workflow_callback(
                "wait_for_window_drafts",
                lambda _state: (_ for _ in ()).throw(GraphInterrupt()),
            )({})
    finally:
        reset_progress_callback(token)

    assert [item["event_type"] for item in events] == [
        "workflow.node.started",
        "workflow.node.interrupted",
    ]
    assert events[-1]["stage"] == "planning"
