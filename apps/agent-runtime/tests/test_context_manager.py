import tempfile
import unittest

from app.context.assembler import ContextAssembler
from app.context.cache_store import FileBackedCacheStore, InMemoryCacheStore, LayeredCacheStore
from app.context.compressor import ReferenceCompressor
from app.context.manager import ContextManager
from app.context.models import ContextBudget, ModelContextProfile, ReferenceMaterial


class ContextManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = ModelContextProfile(
            model_id="gpt-5.4",
            provider="openai_compatible",
            max_input_tokens=120,
            max_output_tokens=32,
            reserved_output_tokens=24,
        )
        self.cache_store = InMemoryCacheStore(ttl_seconds=60)
        self.compressor = ReferenceCompressor()
        self.assembler = ContextAssembler()
        self.manager = ContextManager(
            cache_store=self.cache_store,
            compressor=self.compressor,
            assembler=self.assembler,
        )

    def test_build_snapshot_compresses_reference_material_to_fit_budget(self) -> None:
        snapshot = self.manager.build_snapshot(
            task_id="task-1",
            stage="planning",
            instruction="为用户生成一个冷静克制的长篇小说大纲。",
            model_profile=self.profile,
            references=[
                ReferenceMaterial(
                    source_id="ref-1",
                    title="设定集",
                    content="世界观设定。" * 40,
                    priority=10,
                ),
                ReferenceMaterial(
                    source_id="ref-2",
                    title="人物小传",
                    content="角色背景。" * 35,
                    priority=8,
                ),
            ],
            memory_items=["上一轮结论：保留双主角结构。", "禁忌：避免轻喜剧口吻。"],
        )

        self.assertEqual(snapshot.task_id, "task-1")
        self.assertEqual(snapshot.stage, "planning")
        self.assertFalse(snapshot.cache_hit)
        self.assertLessEqual(
            snapshot.packet.estimated_input_tokens,
            snapshot.budget.available_input_tokens,
        )
        self.assertGreaterEqual(len(snapshot.compressed_references), 1)
        self.assertTrue(snapshot.packet.references_text)
        self.assertTrue(snapshot.packet.assembled_text.startswith("任务阶段：planning"))

    def test_build_snapshot_uses_memory_cache_on_repeated_calls(self) -> None:
        references = [
            ReferenceMaterial(
                source_id="ref-1",
                title="素材",
                content="线索A。" * 20,
                priority=5,
            )
        ]

        first_snapshot = self.manager.build_snapshot(
            task_id="task-cache",
            stage="drafting",
            instruction="生成正文。",
            model_profile=self.profile,
            references=references,
            memory_items=["已完成章节摘要：主角决定离开故乡。"],
        )
        second_snapshot = self.manager.build_snapshot(
            task_id="task-cache",
            stage="drafting",
            instruction="生成正文。",
            model_profile=self.profile,
            references=references,
            memory_items=["已完成章节摘要：主角决定离开故乡。"],
        )

        self.assertFalse(first_snapshot.cache_hit)
        self.assertTrue(second_snapshot.cache_hit)
        self.assertEqual(first_snapshot.cache_key, second_snapshot.cache_key)
        self.assertEqual(first_snapshot.packet.assembled_text, second_snapshot.packet.assembled_text)

    def test_context_cache_logs_lookup_hit_and_miss(self) -> None:
        references = [
            ReferenceMaterial(
                source_id="ref-1",
                title="素材",
                content="线索A。" * 20,
                priority=5,
            )
        ]

        with self.assertLogs("app.context.manager", level="DEBUG") as logs:
            self.manager.build_snapshot(
                task_id="task-cache",
                stage="drafting",
                instruction="生成正文。",
                model_profile=self.profile,
                references=references,
                memory_items=["已完成章节摘要：主角决定离开故乡。"],
            )
            self.manager.build_snapshot(
                task_id="task-cache",
                stage="drafting",
                instruction="生成正文。",
                model_profile=self.profile,
                references=references,
                memory_items=["已完成章节摘要：主角决定离开故乡。"],
            )

        log_text = "\n".join(logs.output)
        self.assertIn("上下文缓存查询", log_text)
        self.assertIn("hit=False", log_text)
        self.assertIn("hit=True", log_text)
        self.assertIn("stage=drafting", log_text)

    def test_build_snapshot_rebuilds_when_cached_snapshot_schema_is_stale(self) -> None:
        class StaleCacheStore:
            def __init__(self) -> None:
                self.written_value = None

            def get(self, key: str):
                return {
                    "task_id": "task-cache",
                    "stage": "drafting",
                    "model_id": "gpt-5.4",
                    "cache_key": key,
                    "packet": {"旧字段": "旧缓存结构"},
                }

            def set(self, key: str, value) -> None:
                self.written_value = value

            def clear(self) -> None:
                pass

            def cleanup(self) -> None:
                pass

        cache_store = StaleCacheStore()
        manager = ContextManager(
            cache_store=cache_store,
            compressor=self.compressor,
            assembler=self.assembler,
        )

        snapshot = manager.build_snapshot(
            task_id="task-cache",
            stage="drafting",
            instruction="生成正文。",
            model_profile=self.profile,
            references=[
                ReferenceMaterial(
                    source_id="ref-1",
                    title="素材",
                    content="线索A。" * 20,
                    priority=5,
                )
            ],
            memory_items=["已完成章节摘要：主角决定离开故乡。"],
        )

        self.assertFalse(snapshot.cache_hit)
        self.assertIsNotNone(cache_store.written_value)
        self.assertTrue(snapshot.packet.assembled_text.startswith("任务阶段：drafting"))

    def test_build_snapshot_warns_and_rebuilds_when_cache_read_fails(self) -> None:
        class BrokenReadCacheStore:
            def __init__(self) -> None:
                self.written_value = None

            def get(self, key: str):
                raise RuntimeError("cache read broken")

            def set(self, key: str, value) -> None:
                self.written_value = value

            def clear(self) -> None:
                pass

            def cleanup(self) -> None:
                pass

        cache_store = BrokenReadCacheStore()
        manager = ContextManager(
            cache_store=cache_store,
            compressor=self.compressor,
            assembler=self.assembler,
        )

        with self.assertLogs("app.context.manager", level="WARNING") as logs:
            snapshot = manager.build_snapshot(
                task_id="task-cache",
                stage="drafting",
                instruction="生成正文。",
                model_profile=self.profile,
                references=[
                    ReferenceMaterial(
                        source_id="ref-1",
                        title="素材",
                        content="线索A。" * 20,
                        priority=5,
                    )
                ],
                memory_items=["已完成章节摘要：主角决定离开故乡。"],
            )

        self.assertFalse(snapshot.cache_hit)
        self.assertIsNotNone(cache_store.written_value)
        self.assertIn("读取上下文缓存失败", "\n".join(logs.output))

    def test_build_snapshot_warns_but_returns_snapshot_when_cache_write_fails(self) -> None:
        class BrokenWriteCacheStore:
            def get(self, key: str):
                return None

            def set(self, key: str, value) -> None:
                raise RuntimeError("cache write broken")

            def clear(self) -> None:
                pass

            def cleanup(self) -> None:
                pass

        manager = ContextManager(
            cache_store=BrokenWriteCacheStore(),
            compressor=self.compressor,
            assembler=self.assembler,
        )

        with self.assertLogs("app.context.manager", level="WARNING") as logs:
            snapshot = manager.build_snapshot(
                task_id="task-cache",
                stage="drafting",
                instruction="生成正文。",
                model_profile=self.profile,
                references=[
                    ReferenceMaterial(
                        source_id="ref-1",
                        title="素材",
                        content="线索A。" * 20,
                        priority=5,
                    )
                ],
                memory_items=["已完成章节摘要：主角决定离开故乡。"],
            )

        self.assertFalse(snapshot.cache_hit)
        self.assertTrue(snapshot.packet.assembled_text.startswith("任务阶段：drafting"))
        self.assertIn("写入上下文缓存失败", "\n".join(logs.output))

    def test_cache_store_expires_entries_after_ttl(self) -> None:
        current_time = {"value": 100.0}
        cache_store = InMemoryCacheStore(
            ttl_seconds=10,
            time_func=lambda: current_time["value"],
        )

        cache_store.set("demo", {"value": 1})
        self.assertEqual(cache_store.get("demo"), {"value": 1})

        current_time["value"] = 111.0
        self.assertIsNone(cache_store.get("demo"))

    def test_file_backed_cache_store_warns_when_json_is_corrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_store = FileBackedCacheStore(tmp_dir, ttl_seconds=60)
            cache_store.set("demo", {"value": 1})
            cache_store._path_for_key("demo").write_text("{bad json", encoding="utf-8")

            with self.assertLogs("app.context.cache_store", level="WARNING") as logs:
                value = cache_store.get("demo")

        self.assertIsNone(value)
        self.assertIn("读取磁盘缓存失败", "\n".join(logs.output))

    def test_layered_cache_store_warns_and_continues_when_read_layer_fails(self) -> None:
        class BrokenReadStore:
            def get(self, key: str):
                raise RuntimeError("layer read broken")

            def set(self, key: str, value) -> None:
                pass

            def clear(self) -> None:
                pass

            def cleanup(self) -> None:
                pass

        class HitStore:
            def get(self, key: str):
                return {"ok": True}

            def set(self, key: str, value) -> None:
                pass

            def clear(self) -> None:
                pass

            def cleanup(self) -> None:
                pass

        layered_store = LayeredCacheStore([BrokenReadStore(), HitStore()])

        with self.assertLogs("app.context.cache_store", level="WARNING") as logs:
            value = layered_store.get("demo")

        self.assertEqual(value, {"ok": True})
        self.assertIn("缓存层读取失败", "\n".join(logs.output))

    def test_layered_cache_store_warns_and_continues_when_write_layer_fails(self) -> None:
        class BrokenWriteStore:
            def get(self, key: str):
                return None

            def set(self, key: str, value) -> None:
                raise RuntimeError("layer write broken")

            def clear(self) -> None:
                pass

            def cleanup(self) -> None:
                pass

        class RecordingStore:
            def __init__(self) -> None:
                self.writes = []

            def get(self, key: str):
                return None

            def set(self, key: str, value) -> None:
                self.writes.append((key, value))

            def clear(self) -> None:
                pass

            def cleanup(self) -> None:
                pass

        recording_store = RecordingStore()
        layered_store = LayeredCacheStore([BrokenWriteStore(), recording_store])

        with self.assertLogs("app.context.cache_store", level="WARNING") as logs:
            layered_store.set("demo", {"value": 1})

        self.assertEqual(recording_store.writes, [("demo", {"value": 1})])
        self.assertIn("缓存写入失败", "\n".join(logs.output))

    def test_assembler_applies_budget_limit_when_reference_text_is_large(self) -> None:
        budget = ContextBudget.from_profile(self.profile)
        packet = self.assembler.assemble(
            task_id="task-2",
            stage="planning",
            budget=budget,
            instruction="请整理大纲。",
            compressed_references=[
                self.compressor.compress_text(
                    ReferenceMaterial(
                        source_id="ref-1",
                        title="超长素材",
                        content="A" * 1000,
                        priority=1,
                    ),
                    max_chars=80,
                )
            ],
            memory_items=["保留悬疑氛围。"],
        )

        self.assertLessEqual(packet.estimated_input_tokens, budget.available_input_tokens)
        self.assertIn("超长素材", packet.references_text)
        self.assertIn("保留悬疑氛围。", packet.memory_text)


if __name__ == "__main__":
    unittest.main()
