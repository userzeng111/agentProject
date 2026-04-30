import unittest


from app.rag.config import RagConfig
from app.rag.service import RagHit, RagService


class StubSearchBackend:
    def __init__(self, hits=None, error: Exception | None = None) -> None:
        self.hits = list(hits or [])
        self.error = error
        self.calls = []

    def search(self, query: str, top_k: int):
        self.calls.append({"query": query, "top_k": top_k})
        if self.error is not None:
            raise self.error
        return list(self.hits)


class RagServiceTests(unittest.TestCase):
    def test_search_selects_contexts_within_budget(self) -> None:
        backend = StubSearchBackend(
            hits=[
                RagHit(doc_id="1", content="甲" * 10, score=0.91, metadata={"source_path": "a.txt"}),
                RagHit(doc_id="2", content="乙" * 10, score=0.82, metadata={"source_path": "b.txt"}),
                RagHit(doc_id="3", content="丙" * 10, score=0.73, metadata={"source_path": "c.txt"}),
            ]
        )
        service = RagService(
            RagConfig(enabled=True, top_k=3, max_context_chars=15),
            search_backend=backend,
        )

        result = service.search("苹果是什么")

        self.assertEqual(len(result.hits), 3)
        self.assertEqual(result.selected_contexts, ["甲" * 10])
        self.assertIsNone(result.error)
        self.assertEqual(backend.calls[0]["query"], "苹果是什么")

    def test_search_degrades_gracefully_when_backend_is_unavailable(self) -> None:
        backend = StubSearchBackend(error=FileNotFoundError("index.faiss not found"))
        service = RagService(
            RagConfig(enabled=True, top_k=3, max_context_chars=30),
            search_backend=backend,
        )

        result = service.search("苹果是什么")

        self.assertEqual(result.hits, [])
        self.assertEqual(result.selected_contexts, [])
        self.assertIn("index.faiss", result.error or "")

    def test_select_hits_skips_oversized_first_hit_and_keeps_later_short_hits(self) -> None:
        backend = StubSearchBackend(
            hits=[
                RagHit(doc_id="long", content="甲" * 100, score=0.99),
                RagHit(doc_id="short-1", content="乙" * 10, score=0.80),
                RagHit(doc_id="short-2", content="丙" * 10, score=0.70),
            ]
        )
        service = RagService(
            RagConfig(enabled=True, top_k=3, max_context_chars=25),
            search_backend=backend,
        )

        result = service.search("苹果是什么")

        self.assertEqual(result.selected_contexts, ["乙" * 10, "丙" * 10])
        self.assertEqual([hit.doc_id for hit in result.selected_hits], ["short-1", "short-2"])


if __name__ == "__main__":
    unittest.main()
