from __future__ import annotations

import json
from typing import Any

from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.provider import session as provider_session

from skill_authoring.factory import build_service


class SkillLifecycleManageTool(Tool):
    async def call(
        self,
        params: dict[str, Any],
        session: provider_session.Session,
        query_id: int,
    ) -> str:
        service = build_service(self.plugin)
        operation = str(params.get("operation") or "").strip().lower()
        candidate_id = str(params.get("candidate_id") or "").strip()

        if operation == "retention":
            result = await service.evaluate_retention()
        else:
            if not candidate_id:
                raise ValueError("candidate_id is required for this operation")
            if operation == "record_event":
                result = {
                    "candidate": await service.record_lifecycle_event(
                        candidate_id,
                        {
                            "event_type": params.get("event_type"),
                            "summary": params.get("summary") or "",
                            "weight": params.get("weight"),
                            "metadata": {"query_id": query_id},
                        },
                    )
                }
            elif operation == "evaluate":
                result = {"lifecycle_report": await service.evaluate_lifecycle(candidate_id)}
            elif operation == "apply_action":
                result = {
                    "candidate": await service.apply_lifecycle_action(
                        candidate_id,
                        {
                            "action": params.get("action"),
                            "reason": params.get("summary") or "",
                            "superseded_by": params.get("superseded_by") or "",
                            "operator": "tool",
                        },
                    )
                }
            elif operation == "memory_plan":
                result = await service.memory_coordination_plan(candidate_id)
            else:
                raise ValueError("operation must be record_event, evaluate, apply_action, retention, or memory_plan")

        return json.dumps(result, ensure_ascii=False)
