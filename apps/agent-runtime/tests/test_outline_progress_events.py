from app.domain.models import ReviewDecision
from app.graph.nodes.outline import plan_chapter_batch, review_outline
from app.llm.story_engine import reset_progress_callback, set_progress_callback
from app.settings.config import Settings
from app.storage.database import init_db
from app.storage.db_repository import get_chapter_plan_batch


def test_auto_outline_review_emits_progress_events() -> None:
    events: list[dict] = []
    token = set_progress_callback(events.append)
    try:
        result = review_outline(
            {
                "task_id": "task-progress",
                "auto_review": True,
                "auto_review_policy": {
                    "allow_self_revisions": True,
                    "outline_pass_threshold": 60,
                },
                "normalized_spec": {
                    "mode": "short_story",
                    "prompt": "写一个校园恋爱故事",
                    "genre": "校园恋爱",
                    "style": "",
                },
                "story_plan": {
                    "working_title": "校园心动",
                    "logline": "两个高中生在误会与成长中靠近。",
                    "world_notes": ["现代校园"],
                    "character_notes": ["林浩", "苏静"],
                    "planned_chapter_count": 2,
                    "chapter_plan": [
                        {"number": 1, "title": "初遇", "goal": "建立关系"},
                        {"number": 2, "title": "靠近", "goal": "解决误会"},
                    ],
                },
                "outline_revision_count": 0,
                "outline_phase": "chapter_batches",
                "outline_batch_index": 0,
                "outline_batch_size": 20,
                "outline_total_count": 2,
                "current_batch_chapter_plans": [
                    {"number": 1, "title": "初遇", "goal": "建立关系"},
                    {"number": 2, "title": "靠近", "goal": "解决误会"},
                ],
                "auto_review_trace": [],
            },
            auto_review_executor_available=True,
            execute_auto_review=lambda payload, policy: ReviewDecision(
                approved=True,
                comment="通过",
                reasoning="章节计划可以进入正文。",
                overall_score=86,
            ),
            should_interrupt_manual_review=lambda **kwargs: False,
            interrupt_outline_review=lambda state, comment="": {"approved": True, "comment": comment},
            build_auto_review_summary=lambda **kwargs: {
                "__summary__": True,
                "overall_score": kwargs["decision"].overall_score,
            },
        )
    finally:
        reset_progress_callback(token)

    assert result["approved"] is True
    assert [event["event_type"] for event in events] == [
        "outline.review.started",
        "outline.review.completed",
    ]
    assert events[0]["stage"] == "planning"
    assert events[0]["unit_id"] == "outline-chapter-batches"
    assert events[1]["payload"]["score"] == 86
    assert events[1]["payload"]["approved"] is True


def test_auto_outline_review_approves_current_chapter_plan_batch(tmp_path) -> None:
    init_db(
        tmp_path / "data.db",
        settings=Settings(_env_file=None, SQLITE_JOURNAL_MODE="WAL"),
    )
    state = {
        "task_id": "task-progress",
        "auto_review": True,
        "auto_review_policy": {
            "allow_self_revisions": True,
            "outline_pass_threshold": 60,
        },
        "normalized_spec": {
            "mode": "short_story",
            "prompt": "写一个校园恋爱故事",
            "genre": "校园恋爱",
            "style": "",
        },
        "story_plan": {
            "working_title": "校园心动",
            "logline": "两个高中生在误会与成长中靠近。",
            "world_notes": ["现代校园"],
            "character_notes": ["林浩", "苏静"],
            "planned_chapter_count": 2,
            "chapter_plan": [
                {"number": 1, "title": "初遇", "goal": "建立关系"},
                {"number": 2, "title": "靠近", "goal": "解决误会"},
            ],
        },
        "outline_revision_count": 0,
        "outline_phase": "master",
        "outline_batch_index": 0,
        "outline_batch_size": 20,
        "outline_completed_count": 0,
        "outline_total_count": 2,
        "outline_batch_retry_count": 0,
        "auto_review_trace": [],
    }
    planned = plan_chapter_batch(state, engine=object())
    state.update(planned)

    result = review_outline(
        state,
        auto_review_executor_available=True,
        execute_auto_review=lambda payload, policy: ReviewDecision(
            approved=True,
            comment="通过",
            reasoning="章节计划可以进入正文。",
            overall_score=86,
        ),
        should_interrupt_manual_review=lambda **kwargs: False,
        interrupt_outline_review=lambda state, comment="": {"approved": True, "comment": comment},
        build_auto_review_summary=lambda **kwargs: {
            "__summary__": True,
            "overall_score": kwargs["decision"].overall_score,
        },
    )

    batch = get_chapter_plan_batch("task-progress", 1)

    assert batch is not None
    assert batch.status == "approved"
    assert result["approved"] is True
    assert result["outline_completed_count"] == 2
    assert result["outline_batch_retry_count"] == 0
