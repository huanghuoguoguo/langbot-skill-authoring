from __future__ import annotations

import pytest

from skill_authoring.generator import render_skill_md
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

