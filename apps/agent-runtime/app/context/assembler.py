from __future__ import annotations

from app.context.models import CompressedReference, ContextBudget, ContextPacket, estimate_tokens


class ContextAssembler:
    def assemble(
        self,
        task_id: str,
        stage: str,
        budget: ContextBudget,
        instruction: str,
        compressed_references: list[CompressedReference],
        memory_items: list[str] | None = None,
    ) -> ContextPacket:
        instruction_text = self._clamp_text(instruction.strip(), budget.max_instruction_chars)
        memory_text = self._clamp_text(
            "\n".join(item.strip() for item in (memory_items or []) if item.strip()),
            budget.max_memory_chars,
        )
        references_text = self._clamp_text(
            self._format_references(compressed_references),
            budget.max_reference_chars,
        )
        assembled_text, estimated_tokens, truncated = self._fit_sections(
            stage=stage,
            budget=budget,
            instruction_text=instruction_text,
            memory_text=memory_text,
            references_text=references_text,
        )
        return ContextPacket(
            task_id=task_id,
            stage=stage,
            instruction_text=instruction_text,
            memory_text=memory_text,
            references_text=references_text,
            assembled_text=assembled_text,
            estimated_input_tokens=estimated_tokens,
            truncated=truncated,
        )

    def _fit_sections(
        self,
        stage: str,
        budget: ContextBudget,
        instruction_text: str,
        memory_text: str,
        references_text: str,
    ) -> tuple[str, int, bool]:
        truncated = False
        sections = {
            "instruction_text": instruction_text,
            "memory_text": memory_text,
            "references_text": references_text,
        }
        assembled_text = self._compose(stage, **sections)
        estimated_tokens = estimate_tokens(assembled_text)
        while estimated_tokens > budget.available_input_tokens:
            overflow_chars = max((estimated_tokens - budget.available_input_tokens) * 4, 4)
            if sections["references_text"]:
                sections["references_text"] = self._trim_by_chars(sections["references_text"], overflow_chars)
            elif sections["memory_text"]:
                sections["memory_text"] = self._trim_by_chars(sections["memory_text"], overflow_chars)
            elif sections["instruction_text"]:
                sections["instruction_text"] = self._trim_by_chars(sections["instruction_text"], overflow_chars)
            else:
                break
            truncated = True
            assembled_text = self._compose(stage, **sections)
            estimated_tokens = estimate_tokens(assembled_text)
        return assembled_text, estimated_tokens, truncated

    def _compose(
        self,
        stage: str,
        instruction_text: str,
        memory_text: str,
        references_text: str,
    ) -> str:
        parts = [
            f"任务阶段：{stage}",
            f"用户指令：\n{instruction_text or '无'}",
            f"记忆上下文：\n{memory_text or '无'}",
            f"参考素材：\n{references_text or '无'}",
        ]
        return "\n\n".join(parts)

    def _format_references(self, compressed_references: list[CompressedReference]) -> str:
        blocks: list[str] = []
        for reference in compressed_references:
            blocks.append(f"[{reference.title}]\n{reference.content}")
        return "\n\n".join(blocks)

    def _clamp_text(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        return f"{text[: max_chars - 3]}..."

    def _trim_by_chars(self, text: str, trim_chars: int) -> str:
        if not text:
            return text
        target_length = max(len(text) - trim_chars, 0)
        return self._clamp_text(text, target_length)
