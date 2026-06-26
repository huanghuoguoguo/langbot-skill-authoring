from __future__ import annotations

from typing import Any

from .service import SkillAuthoringService


def build_service(plugin: Any) -> SkillAuthoringService:
    config = plugin.get_config() if plugin else {}
    return SkillAuthoringService(
        plugin.candidate_store,
        max_source_chars=int(config.get("max_source_chars") or 12000),
        retention_deprecate_score=int(config.get("retention_deprecate_score") or 70),
        retention_archive_score=int(config.get("retention_archive_score") or 35),
    )
