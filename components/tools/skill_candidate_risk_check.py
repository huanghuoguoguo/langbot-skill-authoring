from __future__ import annotations

import json
from typing import Any

from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.provider import session as provider_session

from skill_authoring.factory import build_service


class SkillCandidateRiskCheckTool(Tool):
    async def call(
        self,
        params: dict[str, Any],
        session: provider_session.Session,
        query_id: int,
    ) -> str:
        service = build_service(self.plugin)
        report = await service.risk_check(str(params.get("candidate_id") or ""))
        return json.dumps(report, ensure_ascii=False)
