"""
Skill 加载器

从 YAML 文件加载、校验、缓存 Skill 配置。
按 agent 分目录：story_engine/ 和 auto_reviewer/。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from app.agents.models import SkillConfig

logger = logging.getLogger(__name__)


class SkillLoadError(Exception):
    """Skill 加载或校验失败时抛出。"""

    def __init__(self, skill_id: str, path: Path, reason: str) -> None:
        self.skill_id = skill_id
        self.path = path
        self.reason = reason
        super().__init__(f"Skill 加载失败 [{skill_id}] ({path}): {reason}")


def _extract_template_variables(template: str) -> set[str]:
    """从 prompt 模板中提取 {variable} 格式的变量名。"""
    return set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", template))


class SkillLoader:
    """从文件系统加载 Skill YAML 配置。

    每个 agent 一个子目录，目录下每个 .yaml 是一个 skill。
    """

    def __init__(self, skills_root: Path) -> None:
        self._skills_root = skills_root
        self._registry: dict[str, SkillConfig] = {}
        self._load_errors: list[SkillLoadError] = []

    def load_all(self) -> dict[str, SkillConfig]:
        """扫描 skills_root 下所有 YAML 文件，返回注册表。"""
        self._registry.clear()
        self._load_errors.clear()

        if not self._skills_root.exists():
            logger.debug("Skill 根目录不存在，按无外部 Skill 处理: %s", self._skills_root)
            return self._registry

        yaml_files = sorted(self._skills_root.rglob("*.yaml"))
        if not yaml_files:
            logger.debug("未找到 Skill YAML 文件，按内置 prompt fallback: %s", self._skills_root)
            return self._registry

        for yaml_path in yaml_files:
            try:
                config = self._load_single(yaml_path)
                if config.skill_id in self._registry:
                    existing = self._registry[config.skill_id]
                    raise SkillLoadError(
                        config.skill_id,
                        yaml_path,
                        f"skill_id 重复，已存在于 {existing.source_path}",
                    )
                self._registry[config.skill_id] = config
            except SkillLoadError as e:
                self._load_errors.append(e)
                logger.error("Skill 加载失败: %s", e)
            except Exception as e:
                error = SkillLoadError("unknown", yaml_path, str(e))
                self._load_errors.append(error)
                logger.error("Skill 加载异常: %s", e)

        logger.info(
            "已加载 %d 个 Skill（失败 %d 个），根目录: %s",
            len(self._registry),
            len(self._load_errors),
            self._skills_root,
        )
        return self._registry

    def _load_single(self, yaml_path: Path) -> SkillConfig:
        """加载并校验单个 YAML 文件。"""
        raw = yaml_path.read_text(encoding="utf-8")
        if raw.startswith("\ufeff"):
            raw = raw[1:]

        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise SkillLoadError("unknown", yaml_path, "YAML 内容不是有效的字典")

        skill_id = data.get("skill_id", "unknown")
        try:
            config = SkillConfig(**data, source_path=yaml_path)
        except Exception as e:
            raise SkillLoadError(skill_id, yaml_path, f"模型校验失败: {e}") from e

        self._validate_variables(config, yaml_path)
        return config

    def _validate_variables(self, config: SkillConfig, path: Path) -> None:
        """校验 prompt 中的变量与 input_variables 定义是否一致。"""
        system_vars = _extract_template_variables(config.prompt.system)
        human_vars = _extract_template_variables(config.prompt.human)
        template_vars = system_vars | human_vars

        defined_vars = {v.name for v in config.input_variables}

        undefined = template_vars - defined_vars
        if undefined:
            logger.debug(
                "Skill [%s] 模板变量未在 input_variables 中定义: %s（不影响运行）",
                config.skill_id,
                undefined,
            )

        unused = defined_vars - template_vars
        if unused:
            logger.debug(
                "Skill [%s] input_variables 中有未使用的变量: %s",
                config.skill_id,
                unused,
            )

    def get(self, skill_id: str) -> SkillConfig:
        """按 skill_id 获取配置，不存在时抛出 KeyError。"""
        if skill_id not in self._registry:
            raise KeyError(f"Skill 未找到: {skill_id}，可用: {list(self._registry.keys())}")
        return self._registry[skill_id]

    def get_by_group(self, review_group: str) -> list[SkillConfig]:
        """获取同一审核组的所有子 Agent 配置。"""
        return [
            cfg
            for cfg in self._registry.values()
            if cfg.review and cfg.review.review_group == review_group
            and cfg.skill_type == "review"
        ]

    def get_synthesis(self, review_group: str) -> SkillConfig | None:
        """获取指定审核组的综合决策 Agent 配置。"""
        for cfg in self._registry.values():
            if (
                cfg.skill_type == "review_synthesis"
                and cfg.review
                and cfg.review.review_group == review_group
            ):
                return cfg
        return None

    @property
    def registry(self) -> dict[str, SkillConfig]:
        """当前已加载的完整注册表。"""
        return dict(self._registry)

    @property
    def load_errors(self) -> list[SkillLoadError]:
        """加载过程中的错误列表。"""
        return list(self._load_errors)

    def reload(self) -> dict[str, SkillConfig]:
        """清空缓存并重新加载。"""
        return self.load_all()
