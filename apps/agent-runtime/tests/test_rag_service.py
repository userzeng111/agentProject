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

    def test_score_threshold_filters_low_score_hits(self) -> None:
        backend = StubSearchBackend(
            hits=[
                RagHit(doc_id="high", content="高质量结果", score=0.91),
                RagHit(doc_id="mid", content="中等结果", score=0.30),
                RagHit(doc_id="low", content="低质量结果", score=0.29),
            ]
        )
        service = RagService(
            RagConfig(enabled=True, top_k=3, max_context_chars=100),
            search_backend=backend,
            score_threshold=0.3,
        )

        result = service.search("测试")

        self.assertEqual([hit.doc_id for hit in result.hits], ["high", "mid"])
        self.assertEqual(result.selected_contexts, ["高质量结果", "中等结果"])

    def test_dedup_removes_similar_hits_keeps_higher_score(self) -> None:
        backend = StubSearchBackend(
            hits=[
                # 6 个 token 完全包含在 7 个 token 中，Jaccard = 6/7 ≈ 0.857 >= 0.85
                RagHit(doc_id="a", content="苹果 香蕉 橙子 西瓜 梨子 草莓", score=0.95),
                RagHit(doc_id="b", content="苹果 香蕉 橙子 西瓜 梨子 草莓 葡萄", score=0.85),
                RagHit(doc_id="c", content="完全不同的内容", score=0.80),
            ]
        )
        service = RagService(
            RagConfig(enabled=True, top_k=3, max_context_chars=200),
            search_backend=backend,
            score_threshold=0.3,
            dedup_jaccard_threshold=0.85,
        )

        result = service.search("水果")

        self.assertEqual([hit.doc_id for hit in result.hits], ["a", "c"])
        self.assertEqual(result.selected_contexts, ["苹果 香蕉 橙子 西瓜 梨子 草莓", "完全不同的内容"])

    def test_dedup_threshold_can_be_disabled_via_one(self) -> None:
        backend = StubSearchBackend(
            hits=[
                RagHit(doc_id="a", content="苹果 香蕉", score=0.90),
                RagHit(doc_id="b", content="苹果 香蕉", score=0.85),
            ]
        )
        service = RagService(
            RagConfig(enabled=True, top_k=2, max_context_chars=200),
            search_backend=backend,
            dedup_jaccard_threshold=1.0,
        )

        result = service.search("水果")

        # Jaccard=1.0 需要分词集合完全相同，内容相同则去重保留高分
        self.assertEqual([hit.doc_id for hit in result.hits], ["a"])


if __name__ == "__main__":
    unittest.main()
