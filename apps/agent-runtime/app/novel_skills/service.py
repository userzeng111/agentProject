from __future__ import annotations

from pathlib import Path
from typing import Any

from app.style_profiles.service import StyleProfileService

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_WORKFLOW_ROOT = PROJECT_ROOT / "apps" / "agent-runtime" / "app" / "methodology" / "novel-writer-workflow"


class NovelSkillService:
    def __init__(
        self,
        workflow_root: Path | None = None,
        style_root: Path | None = None,
        style_profile_service: StyleProfileService | None = None,
    ) -> None:
        self.workflow_root = workflow_root or DEFAULT_WORKFLOW_ROOT
        self.style_profile_service = style_profile_service or StyleProfileService(style_root=style_root)

    def get_workflow_package(self) -> dict[str, Any] | None:
        entry_path = self.workflow_root / "SKILL.md"
        if not entry_path.is_file():
            return None
        manifest, body = self._load_skill_markdown(entry_path)
        package_id = str(manifest.get("name") or self.workflow_root.name)
        return {
            "id": package_id,
            "kind": "workflow",
            "root_path": str(self.workflow_root),
            "entry_path": str(entry_path),
            "manifest": manifest,
            "compiled_guidance": self._compact_markdown(body, max_lines=16),
            "status": "active",
        }

    def list_style_profiles(self) -> list[dict[str, Any]]:
        return self.style_profile_service.list_profiles()

    def build_runtime_context(
        self,
        *,
        mode: str,
        style_profile_id: str = "",
        custom_style: str = "",
    ) -> dict[str, Any]:
        workflow_package = self.get_workflow_package()
        style_profile = None
        if mode == "style_remix" and style_profile_id.strip():
            style_profile = self.style_profile_service.build_runtime_profile(style_profile_id.strip(), custom_style)
        active_package_ids: list[str] = []
        if workflow_package is not None:
            active_package_ids.append(str(workflow_package["id"]))
        if style_profile is not None:
            active_package_ids.append("bisheng-style")
        return {
            "workflow_guidance": str((workflow_package or {}).get("compiled_guidance") or ""),
            "style_profile_id": str((style_profile or {}).get("id") or style_profile_id),
            "style_profile_name": str((style_profile or {}).get("name") or ""),
            "style_profile": style_profile or {},
            "style_guidance": str((style_profile or {}).get("compiled_summary") or custom_style.strip()),
            "active_package_ids": active_package_ids,
            "active_instance_id": str((style_profile or {}).get("id") or ""),
            "custom_style": custom_style.strip(),
        }

    def _load_skill_markdown(self, path: Path) -> tuple[dict[str, Any], str]:
        raw = path.read_text(encoding="utf-8")
        if raw.startswith("\ufeff"):
            raw = raw[1:]
        if not raw.startswith("---"):
            return {}, raw
        lines = raw.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, raw
        end_index = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end_index = index
                break
        if end_index is None:
            return {}, raw
        import yaml

        frontmatter_raw = "\n".join(lines[1:end_index])
        body = "\n".join(lines[end_index + 1 :]).strip()
        data = yaml.safe_load(frontmatter_raw) or {}
        return (data if isinstance(data, dict) else {}), body

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
