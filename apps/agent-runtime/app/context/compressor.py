from __future__ import annotations

from app.context.models import CompressedReference, ReferenceMaterial


class ReferenceCompressor:
    def compress_text(self, reference: ReferenceMaterial, max_chars: int) -> CompressedReference:
        normalized_limit = max(max_chars, 0)
        original_chars = len(reference.content)
        if original_chars <= normalized_limit:
            content = reference.content
            was_compressed = False
            strategy = "full_text"
        elif normalized_limit <= 3:
            content = reference.content[:normalized_limit]
            was_compressed = True
            strategy = "hard_truncate"
        else:
            content = f"{reference.content[: normalized_limit - 3]}..."
            was_compressed = True
            strategy = "truncate_tail"
        return CompressedReference(
            source_id=reference.source_id,
            title=reference.title,
            priority=reference.priority,
            content=content,
            original_chars=original_chars,
            compressed_chars=len(content),
            was_compressed=was_compressed,
            strategy=strategy,
        )

    def compress_references(
        self,
        references: list[ReferenceMaterial],
        max_total_chars: int,
    ) -> list[CompressedReference]:
        if not references:
            return []
        remaining_chars = max(max_total_chars, 0)
        ordered = sorted(
            enumerate(references),
            key=lambda item: (-item[1].priority, item[0]),
        )
        compressed_pairs: list[tuple[int, CompressedReference]] = []
        for index, (original_index, reference) in enumerate(ordered):
            remaining_items = len(ordered) - index
            if remaining_chars <= 0:
                compressed = self.compress_text(reference, 0)
            else:
                allocation = max(remaining_chars // remaining_items, 48)
                compressed = self.compress_text(reference, allocation)
            compressed_pairs.append((original_index, compressed))
            remaining_chars -= compressed.compressed_chars
        compressed_pairs.sort(key=lambda item: item[0])
        return [item[1] for item in compressed_pairs]
