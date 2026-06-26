from __future__ import annotations

import json

import pytest

from components.event_listener.skill_deposition_listener import (
    DEPOSITED_QUERY_VAR,
    SkillDepositionListener,
)
from skill_authoring.generator import render_skill_md
from components.tools.skill_auto_deposit import _config_bool
from langbot_plugin.api.entities import context, events
from langbot_plugin.api.entities.builtin.provider.session import LauncherTypes, Session
from main import SkillAuthoringPlugin
from skill_authoring.post_response import decide_post_response_candidate
from skill_authoring.service import SkillAuthoringService
from skill_authoring.store import CandidateStore


class FakeSkillAuthoringPlugin(SkillAuthoringPlugin):
    def __init__(self, config: dict):
        self._config = config
        self.storage: dict[str, bytes] = {}
        self.candidate_store = CandidateStore(self)
        self.plugin_runtime_handler = object()

    def get_config(self) -> dict:
        return self._config

    async def get_plugin_storage(self, key: str) -> bytes:
        if key not in self.storage:
            raise KeyError(key)
        return self.storage[key]

    async def set_plugin_storage(self, key: str, value: bytes) -> None:
        self.storage[key] = value


class FakeQueryAPI:
    def __init__(self, query_vars: dict):
        self.query_vars = query_vars
        self.set_vars: dict[str, object] = {}

    async def get_query_vars(self) -> dict:
        return self.query_vars

    async def set_query_var(self, key: str, value: object) -> None:
        self.set_vars[key] = value
        self.query_vars[key] = value


def _normal_response_context(
    *,
    user_text: str,
    response_text: str,
    launcher_type: LauncherTypes = LauncherTypes.PERSON,
    funcs_called: list[str] | None = None,
) -> context.EventContext:
    event = events.NormalMessageResponded(
        launcher_type=launcher_type.value,
        launcher_id="launcher-1",
        sender_id="sender-1",
        session=Session(launcher_type=launcher_type, launcher_id="launcher-1"),
        prefix="",
        response_text=response_text,
        finish_reason="stop",
        funcs_called=funcs_called or [],
    )
    return context.EventContext(
        query_id=42,
        event_name="NormalMessageResponded",
        event=event,
    )


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
    assert candidate["provenance"]["origin"] == "manual"
    assert candidate["protected"] is False

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


def test_post_response_decision_accepts_explicit_deposition() -> None:
    decision = decide_post_response_candidate(
        user_text="请把这个流程沉淀一下",
        response_text=(
            "1. Run pytest for the plugin.\n"
            "2. Inspect the LangBot plugin logs.\n"
            "3. Verify the Page API and export package before calling register_skill."
        ),
        funcs_called=["skill_candidate_create"],
    )

    assert decision.should_create is True
    assert decision.explicit_request is True
    assert decision.confidence >= 0.72
    assert "# User Message" in decision.source_excerpt


def test_post_response_decision_rejects_low_signal_meta_question() -> None:
    decision = decide_post_response_candidate(
        user_text="这个怎么实现的？给我讲讲。",
        response_text="它是通过事件监听和配置开关完成的，具体实现需要看插件结构。",
    )

    assert decision.should_create is False
    assert decision.confidence < 0.72


@pytest.mark.asyncio
async def test_post_response_listener_disabled_by_default(monkeypatch) -> None:
    fake_api = FakeQueryAPI({"user_message_text": "请把这个流程沉淀一下"})
    monkeypatch.setattr(
        "components.event_listener.skill_deposition_listener.QueryBasedAPIProxy",
        lambda **_: fake_api,
    )
    plugin = FakeSkillAuthoringPlugin(
        {
            "auto_deposition_enabled": False,
            "post_response_candidate_enabled": True,
        }
    )
    listener = SkillDepositionListener()
    listener.plugin = plugin

    await listener._create_post_response_candidate(
        _normal_response_context(
            user_text="请把这个流程沉淀一下",
            response_text="1. Run pytest. 2. Verify logs. 3. Export the skill candidate.",
        )
    )

    assert CandidateStore.KEY not in plugin.storage
    assert DEPOSITED_QUERY_VAR not in fake_api.set_vars


@pytest.mark.asyncio
async def test_post_response_listener_creates_candidate_when_enabled(monkeypatch) -> None:
    fake_api = FakeQueryAPI(
        {
            "user_message_text": "请把这个 LangBot 插件调试流程沉淀一下",
            "sender_name": "Alice",
            "_ltm_context": {"speaker": {"id": "sender-1", "name": "Alice"}, "episodes": []},
        }
    )
    monkeypatch.setattr(
        "components.event_listener.skill_deposition_listener.QueryBasedAPIProxy",
        lambda **_: fake_api,
    )
    plugin = FakeSkillAuthoringPlugin(
        {
            "auto_deposition_enabled": True,
            "post_response_candidate_enabled": True,
            "post_response_private_only": True,
        }
    )
    listener = SkillDepositionListener()
    listener.plugin = plugin

    await listener._create_post_response_candidate(
        _normal_response_context(
            user_text="请把这个 LangBot 插件调试流程沉淀一下",
            response_text=(
                "1. Run pytest for the plugin.\n"
                "2. Inspect LangBot plugin runtime logs.\n"
                "3. Verify the Page API and exported SKILL.md before runtime registration."
            ),
            funcs_called=["skill_candidate_create"],
        )
    )

    stored = json.loads(plugin.storage[CandidateStore.KEY].decode("utf-8"))
    assert len(stored) == 1
    candidate = next(iter(stored.values()))
    assert candidate["source_type"] == "post_response"
    assert candidate["provenance"]["origin"] == "agent_review"
    assert candidate["provenance"]["post_response_decision"]["should_create"] is True
    assert candidate["provenance"]["longterm_memory_context_available"] is True
    assert candidate["auto_curation_eligible"] is True
    assert fake_api.set_vars[DEPOSITED_QUERY_VAR]["candidate_id"] == candidate["id"]


@pytest.mark.asyncio
async def test_post_response_listener_skips_group_by_default(monkeypatch) -> None:
    fake_api = FakeQueryAPI({"user_message_text": "沉淀一下这个流程"})
    monkeypatch.setattr(
        "components.event_listener.skill_deposition_listener.QueryBasedAPIProxy",
        lambda **_: fake_api,
    )
    plugin = FakeSkillAuthoringPlugin(
        {
            "auto_deposition_enabled": True,
            "post_response_candidate_enabled": True,
            "post_response_private_only": True,
        }
    )
    listener = SkillDepositionListener()
    listener.plugin = plugin

    await listener._create_post_response_candidate(
        _normal_response_context(
            user_text="沉淀一下这个流程",
            response_text="1. Run pytest. 2. Verify logs. 3. Export the package.",
            launcher_type=LauncherTypes.GROUP,
        )
    )

    assert CandidateStore.KEY not in plugin.storage
    assert DEPOSITED_QUERY_VAR not in fake_api.set_vars


@pytest.mark.asyncio
async def test_post_response_auto_export_respects_risk_policy(monkeypatch) -> None:
    fake_api = FakeQueryAPI({"user_message_text": "把这个有凭证的流程沉淀一下"})
    monkeypatch.setattr(
        "components.event_listener.skill_deposition_listener.QueryBasedAPIProxy",
        lambda **_: fake_api,
    )
    plugin = FakeSkillAuthoringPlugin(
        {
            "auto_deposition_enabled": True,
            "post_response_candidate_enabled": True,
            "post_response_auto_export": True,
            "auto_deposition_policy": "allow_warn",
        }
    )
    listener = SkillDepositionListener()
    listener.plugin = plugin

    await listener._create_post_response_candidate(
        _normal_response_context(
            user_text="把这个有凭证的流程沉淀一下",
            response_text=(
                "1. Set token=sk-abcdefghijklmnopqrstuvwxyz1234567890.\n"
                "2. Run pytest.\n"
                "3. Export the package only after checking the risk report."
            ),
        )
    )

    stored = json.loads(plugin.storage[CandidateStore.KEY].decode("utf-8"))
    candidate = next(iter(stored.values()))
    assert candidate["risk_report"]["status"] == "blocked"
    assert candidate["status"] == "draft"
    assert fake_api.set_vars[DEPOSITED_QUERY_VAR]["auto_exported"] is False


@pytest.mark.asyncio
async def test_post_response_auto_export_publishes_low_risk_package(monkeypatch) -> None:
    fake_api = FakeQueryAPI({"user_message_text": "把这个插件 QA 流程沉淀一下"})
    monkeypatch.setattr(
        "components.event_listener.skill_deposition_listener.QueryBasedAPIProxy",
        lambda **_: fake_api,
    )
    plugin = FakeSkillAuthoringPlugin(
        {
            "auto_deposition_enabled": True,
            "post_response_candidate_enabled": True,
            "post_response_auto_export": True,
            "auto_deposition_policy": "allow_warn",
            "auto_deposition_reviewer": "post-response-test",
        }
    )
    listener = SkillDepositionListener()
    listener.plugin = plugin

    await listener._create_post_response_candidate(
        _normal_response_context(
            user_text="把这个插件 QA 流程沉淀一下",
            response_text=(
                "1. Run pytest for the plugin.\n"
                "2. Inspect runtime logs for plugin loading errors.\n"
                "3. Verify the Page API and exported SKILL.md before registration."
            ),
            funcs_called=["skill_candidate_create"],
        )
    )

    stored = json.loads(plugin.storage[CandidateStore.KEY].decode("utf-8"))
    candidate = next(iter(stored.values()))
    assert candidate["status"] == "published"
    assert candidate["exported_package"]["SKILL.md"]
    assert candidate["reviews"][-1]["reviewer"] == "post-response-test"
    assert fake_api.set_vars[DEPOSITED_QUERY_VAR]["auto_exported"] is True


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
    assert "references/provenance.json" in exported["package"]
    assert "references/learning-decision.json" in exported["package"]
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
async def test_auto_deposit_marks_candidate_curation_eligible() -> None:
    service = SkillAuthoringService(CandidateStore())
    result = await service.auto_deposit(
        {
            "title": "Reusable plugin QA workflow",
            "source_text": "Step 1: run pytest. Step 2: verify plugin page.",
        },
        enabled=True,
    )

    candidate = result["candidate"]
    assert candidate["provenance"]["origin"] == "auto_deposition"
    assert candidate["auto_curation_eligible"] is True
    assert candidate["lifecycle_report"]["auto_apply_allowed"] is False


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


@pytest.mark.asyncio
async def test_lifecycle_negative_feedback_suggests_deprecation() -> None:
    service = SkillAuthoringService(CandidateStore())
    candidate = await service.create_candidate(
        {
            "title": "Noisy workflow",
            "source_text": "Run the same debug steps for every unrelated task.",
        }
    )
    await service.review(candidate["id"], decision="approve", reviewer="tester")
    await service.export(candidate["id"])

    updated = await service.record_lifecycle_event(
        candidate["id"],
        {
            "event_type": "negative_feedback",
            "summary": "User said this Skill was triggered in the wrong context.",
        },
    )

    assert updated["lifecycle_report"]["action"] == "deprecate"
    assert updated["lifecycle_report"]["score"] <= 70


@pytest.mark.asyncio
async def test_lifecycle_security_issue_suggests_archive() -> None:
    service = SkillAuthoringService(CandidateStore())
    candidate = await service.create_candidate(
        {
            "title": "Unsafe workflow",
            "source_text": "Run verification steps.",
        }
    )
    await service.review(candidate["id"], decision="approve", reviewer="tester")
    await service.export(candidate["id"])

    updated = await service.record_lifecycle_event(
        candidate["id"],
        {
            "event_type": "security_issue",
            "summary": "Post-publication review found credential leakage risk.",
        },
    )

    assert updated["lifecycle_report"]["action"] == "archive"


@pytest.mark.asyncio
async def test_lifecycle_apply_supersede_records_replacement() -> None:
    service = SkillAuthoringService(CandidateStore())
    candidate = await service.create_candidate(
        {"title": "Old debug workflow", "source_text": "Run old steps."}
    )
    await service.review(candidate["id"], decision="approve", reviewer="tester")
    await service.export(candidate["id"])

    updated = await service.apply_lifecycle_action(
        candidate["id"],
        {
            "action": "supersede",
            "superseded_by": "new-debug-workflow",
            "reason": "New Skill covers this workflow with safer checks.",
        },
    )

    assert updated["lifecycle_status"] == "superseded"
    assert updated["superseded_by"] == "new-debug-workflow"


@pytest.mark.asyncio
async def test_protected_candidate_requires_force_for_archive() -> None:
    service = SkillAuthoringService(CandidateStore())
    candidate = await service.create_candidate(
        {
            "title": "Runtime registered skill",
            "source_text": "Run known production steps.",
            "source_type": "runtime_registered",
        }
    )

    assert candidate["protected"] is True
    with pytest.raises(ValueError, match="candidate is protected"):
        await service.apply_lifecycle_action(
            candidate["id"],
            {"action": "archive", "reason": "testing protection"},
        )

    archived = await service.apply_lifecycle_action(
        candidate["id"],
        {"action": "archive", "reason": "human approved", "force": True},
    )
    assert archived["lifecycle_status"] == "archived"


@pytest.mark.asyncio
async def test_export_package_contains_learning_decision() -> None:
    service = SkillAuthoringService(CandidateStore())
    candidate = await service.create_candidate(
        {
            "title": "Plugin QA workflow",
            "source_text": "Step 1: run pytest. Step 2: verify page API.",
            "source_ref": {"type": "run", "id": "qa_1"},
        }
    )
    await service.review(candidate["id"], decision="approve", reviewer="tester")
    exported = await service.export(candidate["id"])

    decision = json.loads(exported["package"]["references/learning-decision.json"])
    provenance = json.loads(exported["package"]["references/provenance.json"])

    assert decision["schema_version"] == "learning-decision/v1"
    assert decision["asset_type"] == "skill"
    assert decision["memory_action"] == "write_l2_summary_optional"
    assert provenance["provenance"]["origin"] == "manual"


@pytest.mark.asyncio
async def test_memory_coordination_routes_preferences_to_l1() -> None:
    service = SkillAuthoringService(CandidateStore())
    candidate = await service.create_candidate(
        {
            "title": "User preference",
            "source_text": "Alice prefers concise technical answers.",
        }
    )

    plan = await service.memory_coordination_plan(candidate["id"])

    assert plan["primary_asset"] == "memory_l1"
    assert plan["memory_action"] == "update_profile"
    assert plan["learning_decision"]["schema_version"] == "learning-decision/v1"
    assert plan["longterm_memory_suggestions"][0]["tool"] == "update_profile"


@pytest.mark.asyncio
async def test_memory_coordination_routes_workflow_to_skill() -> None:
    service = SkillAuthoringService(CandidateStore())
    candidate = await service.create_candidate(
        {
            "title": "Plugin install debug workflow",
            "source_text": "Step 1: install plugin. Step 2: verify page API. Step 3: run pytest.",
        }
    )

    plan = await service.memory_coordination_plan(candidate["id"])

    assert plan["primary_asset"] == "skill"
    assert plan["memory_action"] == "write_l2_summary_optional"
    assert plan["longterm_memory_suggestions"][0]["tool"] == "remember"
