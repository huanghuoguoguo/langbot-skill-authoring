from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SourceRef:
    type: str
    id: str
    title: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceRef:
        return cls(
            type=str(data.get("type") or "note"),
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "id": self.id, "title": self.title}


@dataclass
class RiskFinding:
    severity: str
    code: str
    message: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskFinding:
        return cls(
            severity=str(data.get("severity") or "info"),
            code=str(data.get("code") or "unknown"),
            message=str(data.get("message") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass
class RiskReport:
    status: str = "pass"
    findings: list[RiskFinding] = field(default_factory=list)
    checked_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskReport:
        return cls(
            status=str(data.get("status") or "pass"),
            findings=[RiskFinding.from_dict(item) for item in data.get("findings", [])],
            checked_at=str(data.get("checked_at") or utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [item.to_dict() for item in self.findings],
            "checked_at": self.checked_at,
        }


@dataclass
class SkillDraft:
    name: str
    display_name: str
    description: str
    when_to_use: str
    when_not_to_use: str
    procedure: str
    pitfalls: str
    verification: str
    required_tools: list[str] = field(default_factory=list)
    required_permissions: list[str] = field(default_factory=list)
    version: str = "0.1.0"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillDraft:
        return cls(
            name=str(data.get("name") or ""),
            display_name=str(data.get("display_name") or data.get("name") or ""),
            description=str(data.get("description") or ""),
            when_to_use=str(data.get("when_to_use") or ""),
            when_not_to_use=str(data.get("when_not_to_use") or ""),
            procedure=str(data.get("procedure") or data.get("instructions") or ""),
            pitfalls=str(data.get("pitfalls") or ""),
            verification=str(data.get("verification") or ""),
            required_tools=[str(item) for item in data.get("required_tools", [])],
            required_permissions=[
                str(item) for item in data.get("required_permissions", [])
            ],
            version=str(data.get("version") or "0.1.0"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "when_not_to_use": self.when_not_to_use,
            "procedure": self.procedure,
            "pitfalls": self.pitfalls,
            "verification": self.verification,
            "required_tools": list(self.required_tools),
            "required_permissions": list(self.required_permissions),
            "version": self.version,
        }


@dataclass
class ReviewRecord:
    reviewer: str
    decision: str
    comment: str = ""
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewRecord:
        return cls(
            reviewer=str(data.get("reviewer") or ""),
            decision=str(data.get("decision") or ""),
            comment=str(data.get("comment") or ""),
            created_at=str(data.get("created_at") or utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "decision": self.decision,
            "comment": self.comment,
            "created_at": self.created_at,
        }


@dataclass
class SkillCandidate:
    id: str
    title: str
    source_type: str
    source_ref: SourceRef
    source_excerpt: str
    draft: SkillDraft
    status: str = "draft"
    risk_report: RiskReport = field(default_factory=RiskReport)
    reviews: list[ReviewRecord] = field(default_factory=list)
    created_by: str = "plugin"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    published_skill_name: str | None = None
    exported_package: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillCandidate:
        return cls(
            id=str(data["id"]),
            title=str(data.get("title") or ""),
            source_type=str(data.get("source_type") or "note"),
            source_ref=SourceRef.from_dict(data.get("source_ref", {})),
            source_excerpt=str(data.get("source_excerpt") or ""),
            draft=SkillDraft.from_dict(data.get("draft", {})),
            status=str(data.get("status") or "draft"),
            risk_report=RiskReport.from_dict(data.get("risk_report", {})),
            reviews=[ReviewRecord.from_dict(item) for item in data.get("reviews", [])],
            created_by=str(data.get("created_by") or "plugin"),
            created_at=str(data.get("created_at") or utc_now()),
            updated_at=str(data.get("updated_at") or utc_now()),
            published_skill_name=data.get("published_skill_name"),
            exported_package=data.get("exported_package"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "source_type": self.source_type,
            "source_ref": self.source_ref.to_dict(),
            "source_excerpt": self.source_excerpt,
            "draft": self.draft.to_dict(),
            "status": self.status,
            "risk_report": self.risk_report.to_dict(),
            "reviews": [item.to_dict() for item in self.reviews],
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "published_skill_name": self.published_skill_name,
            "exported_package": self.exported_package,
        }

