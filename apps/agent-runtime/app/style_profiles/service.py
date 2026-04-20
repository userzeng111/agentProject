from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_STYLE_ROOT = PROJECT_ROOT / "NoteStyle" / "bisheng-style"
RULE_ORDER = [
    "language",
    "narrative",
    "character",
    "plot",
    "emotion",
    "scene",
    "dialogue",
    "constraints",
    "encoding",
]
RULE_LABELS = {
    "language": "语言",
    "narrative": "叙事",
    "character": "人物",
    "plot": "情节",
    "emotion": "情感",
    "scene": "场景",
    "dialogue": "对话",
    "constraints": "硬约束",
    "encoding": "编码",
}


class StyleProfileService:
    def __init__(self, style_root: Path | None = None) -> None:
        self.style_root = style_root or DEFAULT_STYLE_ROOT
        self.registry_path = self.style_root / "instances" / "registry.yaml"

    def list_profiles(self) -> list[dict[str, Any]]:
        items = self._load_registry()
        profiles: list[dict[str, Any]] = []
        for item in items:
            profile_id = str(item.get("instance_id") or "").strip()
            instance_dir = self._instance_dir(item)
            if not profile_id or str(item.get("status") or "").strip() != "active" or not instance_dir.is_dir():
                continue
            manifest = self._load_manifest(instance_dir / "manifest.yaml")
            profiles.append(
                {
                    "id": profile_id,
                    "name": str(manifest.get("name") or item.get("name") or profile_id),
                    "source_novel": str(manifest.get("source_novel") or item.get("source_novel") or ""),
                    "source_author": str(manifest.get("source_author") or item.get("source_author") or ""),
                    "genre": str(manifest.get("genre") or item.get("genre") or ""),
                    "description": str(manifest.get("description") or item.get("description") or ""),
                    "fidelity_score": int(manifest.get("fidelity_score") or item.get("fidelity_score") or 0),
                    "trigger_keywords": [
                        str(keyword).strip()
                        for keyword in (item.get("trigger_keywords") or [])
                        if str(keyword).strip()
                    ],
                }
            )
        return profiles

    def build_runtime_profile(self, profile_id: str, custom_style: str = "") -> dict[str, Any] | None:
        profile = next((item for item in self.list_profiles() if item["id"] == profile_id), None)
        if profile is None:
            return None
        rule_sections = self._load_rule_sections(profile_id)
        compiled_summary = self._compile_summary(profile, rule_sections, custom_style)
        return {
            **profile,
            "custom_style": custom_style.strip(),
            "rule_sections": rule_sections,
            "compiled_summary": compiled_summary,
        }

    def _load_registry(self) -> list[dict[str, Any]]:
        if not self.registry_path.is_file():
            return []
        raw = self.registry_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
        items = data.get("instances") if isinstance(data, dict) else []
        return items if isinstance(items, list) else []

    def _instance_dir(self, item: dict[str, Any]) -> Path:
        relative = str(item.get("path") or "").strip()
        if relative:
            return self.style_root / relative
        profile_id = str(item.get("instance_id") or "").strip()
        return self.style_root / "instances" / profile_id

    def _load_rule_sections(self, profile_id: str) -> dict[str, str]:
        instance_dir = self.style_root / "instances" / profile_id / "rules"
        sections: dict[str, str] = {}
        for key in RULE_ORDER:
            path = instance_dir / f"{key}.md"
            if not path.is_file():
                continue
            sections[key] = self._compact_markdown(path.read_text(encoding="utf-8"))
        return sections

    def _load_manifest(self, manifest_path: Path) -> dict[str, Any]:
        if not manifest_path.is_file():
            return {}
        raw = manifest_path.read_text(encoding="utf-8")
        documents = list(yaml.safe_load_all(raw))
        for document in documents:
            if isinstance(document, dict):
                return document
        return {}

    def _compact_markdown(self, raw: str, max_lines: int = 8) -> str:
        lines: list[str] = []
        for line in raw.splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            if cleaned.startswith("#"):
                cleaned = cleaned.lstrip("#").strip()
            cleaned = cleaned.replace("**", "")
            lines.append(cleaned)
            if len(lines) >= max_lines:
                break
        return "；".join(lines)

    def _compile_summary(
        self,
        profile: dict[str, Any],
        rule_sections: dict[str, str],
        custom_style: str,
    ) -> str:
        blocks = [
            f"实例：{profile['name']}（原作《{profile['source_novel']}》，作者 {profile['source_author']}）",
            f"定位：{profile['description']}",
        ]
        for key in RULE_ORDER:
            content = rule_sections.get(key)
            if not content:
                continue
            blocks.append(f"{RULE_LABELS[key]}规则：{content}")
        if custom_style.strip():
            blocks.append(f"补充要求：{custom_style.strip()}")
        return "\n".join(blocks)
