import unittest

from app.graph.main_graph import build_graph
from app.workflow.callbacks import WorkflowCallbacks
from app.workflow.engine import NovelWorkflowEngine


def _passthrough(state):
    return {}


def _cancel_from_outline_review(state):
    return {"cancelled": True}


class CancelRecorder:
    def __init__(self) -> None:
        self.called = False

    def __call__(self, state):
        self.called = True
        return {"cancelled": True}


def _callbacks(cancel_task=None) -> WorkflowCallbacks:
    return WorkflowCallbacks(
        normalize_request=_passthrough,
        prepare_outline_context=_passthrough,
        plan_story=_passthrough,
        review_outline=_cancel_from_outline_review,
        revise_outline=_passthrough,
        prepare_chapter_pair_context=_passthrough,
        draft_chapter_pair=_passthrough,
        review_chapter_pair=_passthrough,
        revise_chapter_pair=_passthrough,
        accumulate_chapters=_passthrough,
        verify_full_story=_passthrough,
        review_verification=_passthrough,
        fix_verified_issues=_passthrough,
        assemble_result=_passthrough,
        cancel_task=cancel_task or CancelRecorder(),
    )


class WorkflowCancelRoutesTests(unittest.TestCase):
    def test_main_graph_maps_cancel_task_conditional_branch(self) -> None:
        recorder = CancelRecorder()
        graph = build_graph(callbacks=_callbacks(recorder))

        graph.invoke(
            {
                "task_id": "task-cancel-route-main",
                "input_payload": {},
            },
            config={"configurable": {"thread_id": "task-cancel-route-main"}},
        )

        self.assertTrue(recorder.called)

    def test_workflow_engine_maps_cancel_task_conditional_branch(self) -> None:
        recorder = CancelRecorder()
        engine = NovelWorkflowEngine(_callbacks(recorder))

        engine.start(
            {
                "task_id": "task-cancel-route-engine",
                "input_payload": {},
            },
            config={"configurable": {"thread_id": "task-cancel-route-engine"}},
        )

        self.assertTrue(recorder.called)


if __name__ == "__main__":
    unittest.main()
