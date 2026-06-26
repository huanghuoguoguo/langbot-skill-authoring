from __future__ import annotations

import uuid
from typing import Any

from .generator import build_draft, export_package
from .models import (
    LifecycleEvent,
    LifecycleReport,
    ReviewRecord,
    SkillCandidate,
    SkillDraft,
    SourceRef,
    utc_now,
)
from .risk import scan_text
from .store import CandidateStore


class SkillAuthoringService:
    def __init__(
        self,
        store: CandidateStore,
        *,
        max_source_chars: int = 12000,
        retention_deprecate_score: int = 70,
        retention_archive_score: int = 35,
    ) -> None:
        self.store = store
        self.max_source_chars = max_source_chars
        self.retention_deprecate_score = retention_deprecate_score
        self.retention_archive_score = retention_archive_score

    async def list_candidates(self) -> list[dict[str, Any]]:
        return [candidate.to_dict() for candidate in await self.store.list()]

    async def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        candidate = await self._require(candidate_id)
        return candidate.to_dict()

    async def create_candidate(self, data: dict[str, Any]) -> dict[str, Any]:
        title = str(data.get("title") or "").strip()
        source_text = str(data.get("source_text") or data.get("notes") or "").strip()
        if not title and not source_text:
            raise ValueError("title or source_text is required")
        source_ref = SourceRef.from_dict(data.get("source_ref") or {})
        source_type = str(data.get("source_type") or source_ref.type or "note")
        source_excerpt = source_text[: self.max_source_chars]
        draft = build_draft(
            title=title,
            source_text=source_excerpt,
            source_ref=source_ref,
            requested_name=str(data.get("name") or ""),
        )
        if isinstance(data.get("draft"), dict):
            draft = SkillDraft.from_dict({**draft.to_dict(), **data["draft"]})
        candidate = SkillCandidate(
            id=f"cand_{uuid.uuid4().hex[:12]}",
            title=title or draft.display_name,
            source_type=source_type,
            source_ref=source_ref,
            source_excerpt=source_excerpt,
            draft=draft,
            created_by=str(data.get("created_by") or "plugin"),
        )
        candidate.lifecycle_status = "candidate"
        candidate.risk_report = self._risk_for(candidate)
        await self.store.save(candidate)
        return candidate.to_dict()

    async def auto_deposit(
        self,
        data: dict[str, Any],
        *,
        enabled: bool,
        policy: str = "allow_warn",
        reviewer: str = "auto-deposition",
    ) -> dict[str, Any]:
        if not enabled:
            raise ValueError("auto deposition is disabled by plugin config")

        candidate = await self.create_candidate(data)
        candidate_id = candidate["id"]
        risk_status = candidate["risk_report"]["status"]
        allowed = self._risk_allowed(risk_status, policy)
        result: dict[str, Any] = {
            "mode": "auto_deposition",
            "policy": policy,
            "allowed": allowed,
            "candidate": candidate,
            "risk_disclosure": self._risk_disclosure(risk_status),
            "cost_disclosure": self._cost_disclosure(data),
        }
        if not allowed:
            result["next_action"] = "manual_review_required"
            return result

        reviewed = await self.review(
            candidate_id,
            decision="approve",
            reviewer=reviewer or "auto-deposition",
            comment=(
                "Automatically reviewed by one-click personal assistant "
                f"deposition policy={policy}; risk={risk_status}."
            ),
        )
        exported = await self.export(candidate_id)
        result.update(
            {
                "candidate": exported["candidate"],
                "review": reviewed["reviews"][-1] if reviewed.get("reviews") else None,
                "package": exported["package"],
                "register_skill_hint": exported["register_skill_hint"],
                "next_action": "write_package_then_register_skill",
            }
        )
        return result

    async def update_draft(self, candidate_id: str, draft_patch: dict[str, Any]) -> dict[str, Any]:
        candidate = await self._require(candidate_id)
        candidate.draft = SkillDraft.from_dict({**candidate.draft.to_dict(), **draft_patch})
        candidate.risk_report = self._risk_for(candidate)
        candidate.status = "draft"
        candidate.updated_at = utc_now()
        await self.store.save(candidate)
        return candidate.to_dict()

    async def risk_check(self, candidate_id: str) -> dict[str, Any]:
        candidate = await self._require(candidate_id)
        candidate.risk_report = self._risk_for(candidate)
        candidate.updated_at = utc_now()
        await self.store.save(candidate)
        return candidate.risk_report.to_dict()

    async def review(
        self,
        candidate_id: str,
        *,
        decision: str,
        reviewer: str,
        comment: str = "",
    ) -> dict[str, Any]:
        candidate = await self._require(candidate_id)
        normalized = decision.strip().lower()
        if normalized not in {"approve", "reject", "request_changes", "validate"}:
            raise ValueError("decision must be approve, reject, request_changes, or validate")
        candidate.reviews.append(
            ReviewRecord(reviewer=reviewer or "unknown", decision=normalized, comment=comment)
        )
        if normalized == "approve":
            candidate.status = "validated"
        elif normalized == "validate":
            candidate.status = "validated"
        elif normalized == "reject":
            candidate.status = "rejected"
        else:
            candidate.status = "review"
        candidate.updated_at = utc_now()
        await self.store.save(candidate)
        return candidate.to_dict()

    async def export(self, candidate_id: str) -> dict[str, Any]:
        candidate = await self._require(candidate_id)
        package = export_package(candidate)
        candidate.exported_package = package
        candidate.published_skill_name = candidate.draft.name
        if candidate.status not in {"published", "rejected"}:
            candidate.status = "published" if candidate.status == "validated" else "review"
        if candidate.status == "published" and candidate.lifecycle_status == "candidate":
            candidate.lifecycle_status = "active"
        candidate.updated_at = utc_now()
        await self.store.save(candidate)
        return {
            "candidate": candidate.to_dict(),
            "package": package,
            "register_skill_hint": {
                "write_under": f"/workspace/{candidate.draft.name}",
                "tool": "register_skill",
                "parameters": {"path": f"/workspace/{candidate.draft.name}"},
            },
        }

    async def record_lifecycle_event(
        self,
        candidate_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = await self._require(candidate_id)
        event_type = str(data.get("event_type") or "").strip().lower()
        if not event_type:
            raise ValueError("event_type is required")
        event = LifecycleEvent(
            event_type=event_type,
            summary=str(data.get("summary") or ""),
            weight=int(data.get("weight") or self._default_event_weight(event_type)),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        )
        candidate.lifecycle_events.append(event)
        candidate.lifecycle_report = self._evaluate_lifecycle(candidate)
        candidate.updated_at = utc_now()
        await self.store.save(candidate)
        return candidate.to_dict()

    async def evaluate_lifecycle(self, candidate_id: str) -> dict[str, Any]:
        candidate = await self._require(candidate_id)
        candidate.lifecycle_report = self._evaluate_lifecycle(candidate)
        candidate.updated_at = utc_now()
        await self.store.save(candidate)
        return candidate.lifecycle_report.to_dict()

    async def apply_lifecycle_action(
        self,
        candidate_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = await self._require(candidate_id)
        action = str(data.get("action") or "").strip().lower()
        reason = str(data.get("reason") or "")
        now = utc_now()
        if action not in {"keep", "deprecate", "archive", "supersede", "restore"}:
            raise ValueError("action must be keep, deprecate, archive, supersede, or restore")
        if action == "deprecate":
            candidate.lifecycle_status = "deprecated"
            candidate.deprecated_at = now
        elif action == "archive":
            candidate.lifecycle_status = "archived"
            candidate.archived_at = now
        elif action == "supersede":
            superseded_by = str(data.get("superseded_by") or "").strip()
            if not superseded_by:
                raise ValueError("superseded_by is required for supersede")
            candidate.lifecycle_status = "superseded"
            candidate.superseded_by = superseded_by
            candidate.deprecated_at = now
        elif action == "restore":
            candidate.lifecycle_status = "active"
            candidate.deprecated_at = None
            candidate.archived_at = None
            candidate.superseded_by = None
        else:
            candidate.lifecycle_status = "active" if candidate.status == "published" else "candidate"

        candidate.lifecycle_events.append(
            LifecycleEvent(
                event_type=f"lifecycle.{action}",
                summary=reason,
                weight=0,
                metadata={
                    "superseded_by": candidate.superseded_by,
                    "operator": str(data.get("operator") or "plugin"),
                },
            )
        )
        candidate.lifecycle_report = self._evaluate_lifecycle(candidate)
        candidate.updated_at = now
        await self.store.save(candidate)
        return candidate.to_dict()

    async def evaluate_retention(self) -> dict[str, Any]:
        candidates = await self.store.list()
        items = []
        for candidate in candidates:
            candidate.lifecycle_report = self._evaluate_lifecycle(candidate)
            await self.store.save(candidate)
            items.append(
                {
                    "candidate_id": candidate.id,
                    "skill_name": candidate.draft.name,
                    "status": candidate.status,
                    "lifecycle_status": candidate.lifecycle_status,
                    "report": candidate.lifecycle_report.to_dict(),
                }
            )
        items.sort(key=lambda item: item["report"]["score"])
        return {"retention": items}

    async def memory_coordination_plan(self, candidate_id: str) -> dict[str, Any]:
        candidate = await self._require(candidate_id)
        return self._memory_coordination(candidate)

    async def _require(self, candidate_id: str) -> SkillCandidate:
        candidate = await self.store.get(candidate_id)
        if candidate is None:
            raise ValueError(f"candidate not found: {candidate_id}")
        return candidate

    def _risk_for(self, candidate: SkillCandidate):
        text = "\n".join(
            [
                candidate.title,
                candidate.source_excerpt,
                "\n".join(str(value) for value in candidate.draft.to_dict().values()),
            ]
        )
        return scan_text(text)

    def _default_event_weight(self, event_type: str) -> int:
        weights = {
            "used": 8,
            "success": 12,
            "failure": -18,
            "negative_feedback": -30,
            "positive_feedback": 15,
            "eval_pass": 18,
            "eval_fail": -35,
            "stale": -25,
            "security_issue": -80,
            "memory_conflict": -20,
            "superseded": -45,
        }
        return weights.get(event_type, 0)

    def _evaluate_lifecycle(self, candidate: SkillCandidate) -> LifecycleReport:
        score = 100
        reasons: list[str] = []
        if candidate.risk_report.status == "warn":
            score -= 15
            reasons.append("risk scan has warnings")
        elif candidate.risk_report.status == "blocked":
            score -= 60
            reasons.append("risk scan has blocker findings")

        for event in candidate.lifecycle_events:
            score += event.weight
            if event.weight < 0:
                reasons.append(event.summary or event.event_type)

        if candidate.lifecycle_status in {"deprecated", "archived", "superseded"}:
            reasons.append(f"already {candidate.lifecycle_status}")

        score = max(0, min(150, score))
        action = "keep"
        if candidate.lifecycle_status == "archived":
            action = "archived"
        elif candidate.lifecycle_status == "superseded":
            action = "superseded"
        elif score <= self.retention_archive_score:
            action = "archive"
        elif candidate.lifecycle_status == "deprecated":
            action = "deprecate"
        elif score <= self.retention_deprecate_score:
            action = "deprecate"

        return LifecycleReport(
            score=score,
            action=action,
            reasons=reasons,
        )

    def _memory_coordination(self, candidate: SkillCandidate) -> dict[str, Any]:
        text = "\n".join(
            [
                candidate.title,
                candidate.source_excerpt,
                candidate.draft.when_to_use,
                candidate.draft.procedure,
            ]
        ).lower()
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
        is_profile = any(marker in text for marker in ["prefer", "preference", "likes", "name is", "style"])
        is_episode = any(marker in text for marker in ["today", "yesterday", "deadline", "decided", "recent"])

        if is_procedure:
            primary = "skill"
            memory_action = "write_l2_summary_optional"
        elif is_profile:
            primary = "memory_l1"
            memory_action = "update_profile"
        elif is_episode:
            primary = "memory_l2"
            memory_action = "remember_episode"
        else:
            primary = "manual_review"
            memory_action = "none"

        return {
            "candidate_id": candidate.id,
            "skill_name": candidate.draft.name,
            "primary_asset": primary,
            "memory_action": memory_action,
            "guidance": [
                "Use LongTermMemory L1 for stable user/profile preferences.",
                "Use LongTermMemory L2 for situational facts, decisions, timelines, and correction history.",
                "Use Skill Authoring for reusable procedures that require tools, verification, or workflow sequencing.",
                "When both apply, keep the executable procedure as a Skill and store only a short source/usage summary in L2.",
            ],
        }

    def _risk_allowed(self, risk_status: str, policy: str) -> bool:
        normalized = (policy or "allow_warn").strip().lower()
        if normalized == "allow_blocked":
            return risk_status in {"pass", "warn", "blocked"}
        if normalized == "allow_warn":
            return risk_status in {"pass", "warn"}
        return risk_status == "pass"

    def _risk_disclosure(self, risk_status: str) -> dict[str, Any]:
        return {
            "status": risk_status,
            "risks": [
                "A one-off workflow can be over-generalized into a reusable Skill.",
                "Source evidence may contain secrets, private data, local paths, or internal URLs.",
                "A generated Skill can encourage excessive tool use if its scope is too broad.",
                "Prompt-injection text from logs or webpages can be preserved as long-lived instructions.",
            ],
            "mitigations": [
                "Deterministic risk scanning runs before export.",
                "Generated packages keep source references and risk reports.",
                "Runtime registration still goes through LangBot's existing register_skill path.",
                "Users should inspect blocked or warning candidates before registering them.",
            ],
        }

    def _cost_disclosure(self, data: dict[str, Any]) -> dict[str, Any]:
        source_text = str(data.get("source_text") or data.get("notes") or "")
        estimated_chars = len(source_text)
        return {
            "estimated_source_chars": estimated_chars,
            "llm_calls": 0,
            "storage_writes": "candidate, review record, exported package",
            "runtime_changes": "none until the exported package is written and register_skill is called",
            "human_cost": "user remains responsible for deciding whether the exported Skill should be registered",
        }
