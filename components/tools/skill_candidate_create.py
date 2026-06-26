from __future__ import annotations

from typing import Any

from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.provider import session as provider_session

from skill_authoring.service import SkillAuthoringService


class SkillCandidateCreateTool(Tool):
    async def call(
        self,
        params: dict[str, Any],
        session: provider_session.Session,
        query_id: int,
    ) -> str:
        service = SkillAuthoringService(self.plugin.candidate_store)
        source_type = str(params.get("source_type") or "note")
        candidate = await service.create_candidate(
            {
                "title": params.get("title") or "",
                "source_text": params.get("source_text") or "",
                "source_type": source_type,
                "source_ref": {
                    "type": source_type,
                    "id": str(params.get("source_id") or f"query-{query_id}"),
                },
                "name": params.get("name") or "",
                "created_by": "tool",
            }
        )
        return (
            f"Created skill candidate {candidate['id']} "
            f"({candidate['draft']['name']}) with risk={candidate['risk_report']['status']}."
        )

