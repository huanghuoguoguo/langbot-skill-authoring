from __future__ import annotations

import logging
from typing import Any

from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import context, events
from langbot_plugin.api.proxies.query_based_api import QueryBasedAPIProxy

from skill_authoring.factory import build_service
from skill_authoring.post_response import PostResponseDecision, decide_post_response_candidate

logger = logging.getLogger(__name__)


DEPOSITED_QUERY_VAR = "_skill_authoring_post_response_candidate"


def _config_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _config_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _config_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _risk_allowed(risk_status: str, policy: str) -> bool:
    normalized = (policy or "allow_warn").strip().lower()
    if normalized == "allow_blocked":
        return risk_status in {"pass", "warn", "blocked"}
    if normalized == "allow_warn":
        return risk_status in {"pass", "warn"}
    return risk_status == "pass"


class SkillDepositionListener(EventListener):
    def __init__(self):
        super().__init__()

        @self.handler(events.NormalMessageResponded)
        async def on_normal_message_responded(event_ctx: context.EventContext):
            try:
                await self._create_post_response_candidate(event_ctx)
            except Exception:
                logger.exception("Failed to create post-response Skill candidate")

    async def _create_post_response_candidate(self, event_ctx: context.EventContext) -> None:
        config = self.plugin.get_config() if self.plugin else {}
        if not _config_bool(config.get("auto_deposition_enabled"), False):
            return
        if not _config_bool(config.get("post_response_candidate_enabled"), False):
            return

        event = event_ctx.event
        if not isinstance(event, events.NormalMessageResponded):
            return
        if str(getattr(event, "finish_reason", "") or "").lower() in {
            "error",
            "cancelled",
            "canceled",
            "timeout",
            "content_filter",
        }:
            return
        if _config_bool(config.get("post_response_private_only"), True) and not self._is_private_event(event):
            return

        api = QueryBasedAPIProxy(
            query_id=event_ctx.query_id,
            plugin_runtime_handler=self.plugin.plugin_runtime_handler,
        )
        query_vars = await api.get_query_vars()
        if query_vars.get(DEPOSITED_QUERY_VAR):
            return

        decision = self._decide(event_ctx, event, query_vars, config)
        if not decision.should_create:
            return

        service = build_service(self.plugin)
        title = decision.title or "Post-response learned workflow"
        candidate = await service.create_candidate(
            {
                "title": title,
                "source_text": decision.source_excerpt,
                "source_type": "post_response",
                "source_ref": {
                    "type": "post_response",
                    "id": f"query-{event_ctx.query_id}",
                    "title": title,
                },
                "created_by": "agent_review",
                "origin": "agent_review",
                "auto_curation_eligible": True,
                "provenance": self._provenance(event_ctx, event, query_vars, decision),
            }
        )

        result: dict[str, Any] = {
            "candidate_id": candidate["id"],
            "risk_status": candidate["risk_report"]["status"],
            "confidence": decision.confidence,
            "auto_exported": False,
        }
        if self._auto_export_allowed(config, candidate["risk_report"]["status"]):
            reviewed = await service.review(
                candidate["id"],
                decision="approve",
                reviewer=str(config.get("auto_deposition_reviewer") or "post-response-auto"),
                comment=(
                    "Automatically reviewed by post-response candidate extraction "
                    f"policy={config.get('auto_deposition_policy') or 'allow_warn'}; "
                    f"confidence={decision.confidence:.2f}; risk={candidate['risk_report']['status']}."
                ),
            )
            exported = await service.export(candidate["id"])
            result.update(
                {
                    "candidate_id": exported["candidate"]["id"],
                    "risk_status": exported["candidate"]["risk_report"]["status"],
                    "auto_exported": True,
                    "review_decision": reviewed["reviews"][-1]["decision"] if reviewed.get("reviews") else None,
                    "register_skill_hint": exported["register_skill_hint"],
                }
            )

        await api.set_query_var(DEPOSITED_QUERY_VAR, result)
        logger.info(
            "[SkillAuthoring] post-response candidate created: query_id=%s candidate_id=%s risk=%s auto_exported=%s",
            event_ctx.query_id,
            result["candidate_id"],
            result["risk_status"],
            result["auto_exported"],
        )

    def _decide(
        self,
        event_ctx: context.EventContext,
        event: events.NormalMessageResponded,
        query_vars: dict[str, Any],
        config: dict[str, Any],
    ) -> PostResponseDecision:
        user_text = str(query_vars.get("user_message_text") or query_vars.get("text_message") or "")
        return decide_post_response_candidate(
            user_text=user_text,
            response_text=str(getattr(event, "response_text", "") or ""),
            funcs_called=list(getattr(event, "funcs_called", []) or []),
            min_confidence=_config_float(config.get("post_response_min_confidence"), 0.72),
            explicit_only=_config_bool(config.get("post_response_explicit_only"), False),
            max_source_chars=_config_int(config.get("post_response_max_source_chars"), 6000),
        )

    def _provenance(
        self,
        event_ctx: context.EventContext,
        event: events.NormalMessageResponded,
        query_vars: dict[str, Any],
        decision: PostResponseDecision,
    ) -> dict[str, Any]:
        ltm_context = query_vars.get("_ltm_context")
        return {
            "origin": "agent_review",
            "source_plugin": "skill-authoring",
            "source_event": "NormalMessageResponded",
            "query_id": event_ctx.query_id,
            "launcher_type": str(getattr(event, "launcher_type", "") or ""),
            "launcher_id": str(getattr(event, "launcher_id", "") or ""),
            "sender_id": str(getattr(event, "sender_id", "") or query_vars.get("sender_id", "") or ""),
            "sender_name": str(query_vars.get("sender_name", "") or ""),
            "finish_reason": str(getattr(event, "finish_reason", "") or ""),
            "funcs_called": list(getattr(event, "funcs_called", []) or []),
            "post_response_decision": decision.to_dict(),
            "longterm_memory_context_available": isinstance(ltm_context, dict),
            "longterm_memory_context_summary": self._ltm_context_summary(ltm_context),
        }

    def _is_private_event(self, event: events.NormalMessageResponded) -> bool:
        launcher_type = getattr(event, "launcher_type", "")
        value = getattr(launcher_type, "value", launcher_type)
        if str(value).lower() == "person":
            return True
        session = getattr(event, "session", None)
        session_launcher_type = getattr(session, "launcher_type", "")
        session_value = getattr(session_launcher_type, "value", session_launcher_type)
        return str(session_value).lower() == "person"

    def _auto_export_allowed(self, config: dict[str, Any], risk_status: str) -> bool:
        if not _config_bool(config.get("post_response_auto_export"), False):
            return False
        policy = str(config.get("auto_deposition_policy") or "allow_warn")
        return _risk_allowed(risk_status, policy)

    def _ltm_context_summary(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        speaker = value.get("speaker") if isinstance(value.get("speaker"), dict) else {}
        episodes = value.get("episodes") if isinstance(value.get("episodes"), list) else []
        return {
            "speaker_id": str(speaker.get("id") or ""),
            "speaker_name": str(speaker.get("name") or ""),
            "episode_count": len(episodes),
            "has_session_profile": isinstance(value.get("session_profile"), dict),
            "has_speaker_profile": isinstance(value.get("speaker_profile"), dict),
        }
