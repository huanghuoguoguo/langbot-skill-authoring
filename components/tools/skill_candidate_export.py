from __future__ import annotations

import json
from typing import Any

from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.provider import session as provider_session

from skill_authoring.service import SkillAuthoringService


class SkillCandidateExportTool(Tool):
    async def call(
        self,
        params: dict[str, Any],
        session: provider_session.Session,
        query_id: int,
    ) -> str:
        service = SkillAuthoringService(self.plugin.candidate_store)
        exported = await service.export(str(params.get("candidate_id") or ""))
        return json.dumps(exported, ensure_ascii=False)

