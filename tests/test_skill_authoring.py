from __future__ import annotations

import pytest

from skill_authoring.generator import render_skill_md
from components.tools.skill_auto_deposit import _config_bool
from skill_authoring.service import SkillAuthoringService
from skill_authoring.store import CandidateStore


@pytest.mark.asyncio
async def test_create_candidate_generates_skill_md() -> None:
    service = SkillAuthoringService(CandidateStore())
    candidate = await service.create_candidate(
        {
            "title": "Plugin runtime debug runbook",
            "source_text": "1. Check runtime logs\n2. Run pytest\n3. Verify the Smoke Page",
            "source_ref": {"type": "qa", "id": "plugin-e2e-smoke"},
        }
    )

    assert candidate["draft"]["name"] == "plugin-runtime-debug-runbook"
    assert candidate["risk_report"]["status"] == "pass"

    stored = await service.store.get(candidate["id"])
    assert stored is not None
    skill_md = render_skill_md(stored)
    assert "name: plugin-runtime-debug-runbook" in skill_md
    assert "## When to Use" in skill_md
    assert "plugin-e2e-smoke" in skill_md


def test_config_bool_parses_string_false() -> None:
    assert _config_bool(False) is False
    assert _config_bool("false") is False
    assert _config_bool("true") is True


@pytest.mark.asyncio
async def test_risk_scan_blocks_secret_like_text() -> None:
    service = SkillAuthoringService(CandidateStore())
    candidate = await service.create_candidate(
        {
            "title": "Bad candidate",
            "source_text": "Use token=sk-abcdefghijklmnopqrstuvwxyz1234567890 before running.",
            "source_ref": {"type": "note", "id": "unsafe"},
        }
    )

    assert candidate["risk_report"]["status"] == "blocked"
    codes = {item["code"] for item in candidate["risk_report"]["findings"]}
    assert "secret.openai_key" in codes or "secret.generic_assignment" in codes


@pytest.mark.asyncio
async def test_review_and_export_returns_register_skill_hint() -> None:
    service = SkillAuthoringService(CandidateStore())
    candidate = await service.create_candidate(
        {
            "title": "Sandbox authoring flow",
            "source_text": "Write SKILL.md under /workspace, then call register_skill.",
            "source_ref": {"type": "run", "id": "run_1"},
        }
    )
    reviewed = await service.review(
        candidate["id"],
        decision="approve",
        reviewer="tester",
    )
    assert reviewed["status"] == "validated"

    exported = await service.export(candidate["id"])
    assert "SKILL.md" in exported["package"]
    assert exported["register_skill_hint"]["tool"] == "register_skill"
    assert exported["candidate"]["status"] == "published"


@pytest.mark.asyncio
async def test_auto_deposit_requires_master_switch() -> None:
    service = SkillAuthoringService(CandidateStore())

    with pytest.raises(ValueError, match="auto deposition is disabled"):
        await service.auto_deposit(
            {
                "title": "Personal assistant workflow",
                "source_text": "Summarize the recurring workflow and export a skill.",
            },
            enabled=False,
        )


@pytest.mark.asyncio
async def test_auto_deposit_exports_with_disclosures_when_enabled() -> None:
    service = SkillAuthoringService(CandidateStore())
    result = await service.auto_deposit(
        {
            "title": "Personal assistant workflow",
            "source_text": "Run pytest, inspect logs, then call register_skill after review.",
            "source_ref": {"type": "chat", "id": "chat_1"},
        },
        enabled=True,
        policy="allow_warn",
        reviewer="auto-test",
    )

    assert result["allowed"] is True
    assert result["candidate"]["status"] == "published"
    assert result["register_skill_hint"]["tool"] == "register_skill"
    assert result["cost_disclosure"]["llm_calls"] == 0
    assert result["risk_disclosure"]["risks"]


@pytest.mark.asyncio
async def test_auto_deposit_stops_blocked_candidate_by_default() -> None:
    service = SkillAuthoringService(CandidateStore())
    result = await service.auto_deposit(
        {
            "title": "Unsafe workflow",
            "source_text": "Use token=sk-abcdefghijklmnopqrstuvwxyz1234567890 before running.",
            "source_ref": {"type": "chat", "id": "chat_unsafe"},
        },
        enabled=True,
        policy="allow_warn",
        reviewer="auto-test",
    )

    assert result["allowed"] is False
    assert result["next_action"] == "manual_review_required"
    assert result["candidate"]["status"] == "draft"
