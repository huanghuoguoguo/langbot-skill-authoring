from __future__ import annotations

from typing import Any

from langbot_plugin.api.definition.components.page import Page, PageRequest, PageResponse

from skill_authoring.service import SkillAuthoringService


def _config_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class SkillAuthoringPage(Page):
    def _service(self) -> SkillAuthoringService:
        config = self.plugin.get_config() if self.plugin else {}
        max_source_chars = int(config.get("max_source_chars") or 12000)
        return SkillAuthoringService(
            self.plugin.candidate_store,
            max_source_chars=max_source_chars,
            retention_deprecate_score=int(config.get("retention_deprecate_score") or 70),
            retention_archive_score=int(config.get("retention_archive_score") or 35),
        )

    def _auto_settings(self) -> dict[str, Any]:
        config = self.plugin.get_config() if self.plugin else {}
        return {
            "enabled": _config_bool(config.get("auto_deposition_enabled")),
            "policy": str(config.get("auto_deposition_policy") or "allow_warn"),
            "reviewer": str(config.get("auto_deposition_reviewer") or "auto-deposition"),
        }

    async def handle_api(self, request: PageRequest) -> PageResponse:
        try:
            result = await self._dispatch(request)
            return PageResponse.ok(result)
        except Exception as exc:
            return PageResponse.fail(str(exc))

    async def _dispatch(self, request: PageRequest) -> Any:
        service = self._service()
        endpoint = (request.endpoint or "/").rstrip("/") or "/"
        method = request.method.upper()
        body = request.body or {}

        if endpoint == "/health" and method == "GET":
            return {"ok": True, "plugin": "skill-authoring"}
        if endpoint == "/settings" and method == "GET":
            return {"auto_deposition": self._auto_settings()}
        if endpoint == "/candidates" and method == "GET":
            return {"candidates": await service.list_candidates()}
        if endpoint == "/candidates" and method == "POST":
            return {"candidate": await service.create_candidate(body)}
        if endpoint == "/auto-deposit" and method == "POST":
            settings = self._auto_settings()
            return await service.auto_deposit(
                body,
                enabled=settings["enabled"],
                policy=settings["policy"],
                reviewer=settings["reviewer"],
            )
        if endpoint == "/retention" and method == "GET":
            return await service.evaluate_retention()

        parts = [part for part in endpoint.split("/") if part]
        if len(parts) >= 2 and parts[0] == "candidates":
            candidate_id = parts[1]
            if len(parts) == 2 and method == "GET":
                return {"candidate": await service.get_candidate(candidate_id)}
            if len(parts) == 3 and parts[2] == "draft" and method == "PATCH":
                return {"candidate": await service.update_draft(candidate_id, body)}
            if len(parts) == 3 and parts[2] == "risk" and method == "POST":
                return {"risk_report": await service.risk_check(candidate_id)}
            if len(parts) == 3 and parts[2] == "review" and method == "POST":
                config = self.plugin.get_config() if self.plugin else {}
                reviewer = str(body.get("reviewer") or config.get("default_reviewer") or "operator")
                return {
                    "candidate": await service.review(
                        candidate_id,
                        decision=str(body.get("decision") or ""),
                        reviewer=reviewer,
                        comment=str(body.get("comment") or ""),
                    )
                }
            if len(parts) == 3 and parts[2] == "export" and method == "POST":
                return await service.export(candidate_id)
            if len(parts) == 3 and parts[2] == "lifecycle-events" and method == "POST":
                return {"candidate": await service.record_lifecycle_event(candidate_id, body)}
            if len(parts) == 3 and parts[2] == "lifecycle" and method == "GET":
                return {"lifecycle_report": await service.evaluate_lifecycle(candidate_id)}
            if len(parts) == 3 and parts[2] == "lifecycle" and method == "POST":
                return {"candidate": await service.apply_lifecycle_action(candidate_id, body)}
            if len(parts) == 3 and parts[2] == "memory-plan" and method == "GET":
                return await service.memory_coordination_plan(candidate_id)

        raise ValueError(f"unsupported endpoint: {method} {endpoint}")
