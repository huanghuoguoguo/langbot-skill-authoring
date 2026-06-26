from __future__ import annotations

import json
from typing import Any

from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.provider import session as provider_session

from skill_authoring.service import SkillAuthoringService


def _config_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class SkillAutoDepositTool(Tool):
    async def call(
        self,
        params: dict[str, Any],
        session: provider_session.Session,
        query_id: int,
    ) -> str:
        config = self.plugin.get_config() if self.plugin else {}
        enabled = _config_bool(config.get("auto_deposition_enabled"))
        policy = str(config.get("auto_deposition_policy") or "allow_warn")
        reviewer = str(config.get("auto_deposition_reviewer") or "auto-deposition")

        service = SkillAuthoringService(self.plugin.candidate_store)
        source_type = str(params.get("source_type") or "note")
        result = await service.auto_deposit(
            {
                "title": params.get("title") or "",
                "source_text": params.get("source_text") or "",
                "source_type": source_type,
                "source_ref": {
                    "type": source_type,
                    "id": str(params.get("source_id") or f"query-{query_id}"),
                },
                "name": params.get("name") or "",
                "created_by": "auto-tool",
            },
            enabled=enabled,
            policy=policy,
            reviewer=reviewer,
        )
        return json.dumps(result, ensure_ascii=False)
