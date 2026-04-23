from __future__ import annotations

from app.graph.state import WorkflowState


def assemble_result(state: WorkflowState) -> WorkflowState:
    completed_chapters = state.get("completed_chapters") or []
    story_plan = state.get("story_plan") or {}
    spec = state["normalized_spec"]

    title = story_plan.get("working_title", "未命名")
    logline = story_plan.get("logline", "")

    if spec.get("mode") == "short_story" and len(completed_chapters) <= 3:
        body = "\n\n".join(str(ch.get("content", "")) for ch in completed_chapters)
    else:
        body = "\n\n".join(
            f"## {ch.get('title', '')}\n{ch.get('content', '')}" for ch in completed_chapters
        )

    draft_result = {
        "title": title,
        "summary": logline,
        "body": body,
        "chapters": [
            {
                "number": ch.get("number", i + 1),
                "title": ch.get("title", f"第{i + 1}章"),
                "summary": ch.get("summary", ""),
                "content": ch.get("content", ""),
            }
            for i, ch in enumerate(completed_chapters)
        ],
    }
    return {"draft_result": draft_result}


def cancel_task(state: WorkflowState) -> WorkflowState:
    return {"cancelled": True}
