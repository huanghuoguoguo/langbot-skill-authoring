from __future__ import annotations

from typing import Any

from .models import SkillCandidate


def _candidate_text(candidate: SkillCandidate) -> str:
    return "\n".join(
        [
            candidate.title,
            candidate.source_excerpt,
            candidate.draft.when_to_use,
            candidate.draft.procedure,
        ]
    ).lower()


def learning_decision_for_candidate(candidate: SkillCandidate) -> dict[str, Any]:
    """Classify durable learning as procedural Skill, L1 profile, or L2 episode.

    This is an advisory cross-plugin contract for Skill Authoring and
    LongTermMemory. It returns suggested tool calls, but does not invoke
    another plugin directly.
    """
    text = _candidate_text(candidate)
    is_procedure = any(
        marker in text
        for marker in [
            "step",
            "run ",
            "execute",
            "verify",
            "workflow",
            "call ",
            "install",
            "debug",
        ]
    )
    is_profile = any(
        marker in text
        for marker in [
            "prefer",
            "preference",
            "likes",
            "name is",
            "style",
        ]
    )
    is_episode = any(
        marker in text
        for marker in [
            "today",
            "yesterday",
            "deadline",
            "decided",
            "recent",
        ]
    )

    if is_procedure:
        asset_type = "skill"
        memory_action = "write_l2_summary_optional"
        confidence = 0.82
        reason = "Source describes a reusable procedure with tools, sequence, or verification."
    elif is_profile:
        asset_type = "memory_l1"
        memory_action = "update_profile"
        confidence = 0.76
        reason = "Source looks like a stable user or session preference."
    elif is_episode:
        asset_type = "memory_l2"
        memory_action = "remember_episode"
        confidence = 0.68
        reason = "Source looks like situational or time-bound history."
    else:
        asset_type = "manual_review"
        memory_action = "none"
        confidence = 0.35
        reason = "No strong procedural, profile, or episodic signal was found."

    memory_suggestions: list[dict[str, Any]] = []
    if memory_action == "update_profile":
        memory_suggestions.append(
            {
                "tool": "update_profile",
                "params": {
                    "field": "preferences",
                    "action": "add",
                    "value": candidate.source_excerpt[:500],
                },
                "note": "Review and shorten before applying to L1 profile memory.",
            }
        )
    elif memory_action == "remember_episode":
        memory_suggestions.append(
            {
                "tool": "remember",
                "params": {
                    "content": candidate.source_excerpt[:800],
                    "importance": 0.6,
                    "tags": ["skill-authoring", "episode"],
                },
                "note": "Use for time-bound or situational memory only.",
            }
        )
    elif memory_action == "write_l2_summary_optional":
        memory_suggestions.append(
            {
                "tool": "remember",
                "params": {
                    "content": (
                        f"Skill candidate {candidate.draft.name} was created from "
                        f"{candidate.source_ref.type}:{candidate.source_ref.id}."
                    ),
                    "importance": 0.4,
                    "tags": ["skill-authoring", "skill-created"],
                },
                "note": "Optional compact provenance episode; do not duplicate the full Skill body.",
            }
        )

    return {
        "schema_version": "learning-decision/v1",
        "candidate_id": candidate.id,
        "skill_name": candidate.draft.name,
        "asset_type": asset_type,
        "confidence": confidence,
        "reason": reason,
        "risk_status": candidate.risk_report.status,
        "skill_action": "export_and_register" if asset_type == "skill" else "none",
        "memory_action": memory_action,
        "longterm_memory_suggestions": memory_suggestions,
    }
