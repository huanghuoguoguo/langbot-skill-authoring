from __future__ import annotations

import uuid
from typing import Any

from .generator import build_draft, export_package
from .models import ReviewRecord, SkillCandidate, SkillDraft, SourceRef, utc_now
from .risk import scan_text
from .store import CandidateStore


class SkillAuthoringService:
    def __init__(self, store: CandidateStore, *, max_source_chars: int = 12000) -> None:
        self.store = store
        self.max_source_chars = max_source_chars

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
