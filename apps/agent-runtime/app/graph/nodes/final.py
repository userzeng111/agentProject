from __future__ import annotations

from app.graph.state import WorkflowState


def assemble_result(state: WorkflowState) -> WorkflowState:
    completed_chapters = state.get("completed_chapters") or []
    story_plan = state.get("story_plan") or {}
    spec = state["normalized_spec"]
    planned_total = max(
        int(story_plan.get("planned_chapter_count") or 0),
        len(story_plan.get("chapter_plan") or []),
    )
    if planned_total <= 0:
        raise ValueError("章节计划无效，禁止组装完成结果。")
    if len(completed_chapters) != planned_total:
        raise ValueError(f"正文数量不足，当前 {len(completed_chapters)} 章，计划 {planned_total} 章。")
    for expected_number, chapter in enumerate(completed_chapters, start=1):
        if int(chapter.get("number") or 0) != expected_number:
            raise ValueError("正文章节编号不连续，禁止组装完成结果。")
        if not str(chapter.get("content") or "").strip():
            raise ValueError(f"第 {expected_number} 章正文为空，禁止组装完成结果。")

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
