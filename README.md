# LangBot Skill Authoring

LangBot Skill Authoring is a LangBot plugin for turning run traces, QA evidence,
troubleshooting notes, and operator feedback into reviewable `SKILL.md` drafts.

It is not a replacement for LangBot's Skill runtime. LangBot already owns the
runtime surface: Box-managed `SKILL.md` packages, `activate`,
`register_skill`, Skill CRUD, and sandbox mounts. This plugin adds the missing
authoring loop:

```text
source evidence -> candidate -> risk report -> review -> export/publish package
```

For personal-assistant scenarios, the plugin also has a gated one-click mode:

```text
source evidence or completed turn
  -> auto candidate -> risk report -> policy gate -> optional auto review/export
```

This mode is controlled by the `auto_deposition_enabled` master switch and is
off by default.

## Runtime Boundary

This plugin does not change how LangBot discovers, activates, mounts, or runs a
Skill. Runtime usage remains owned by LangBot core:

- Agents can create a Skill package under `/workspace` and call the built-in
  `register_skill` tool.
- Operators can manage Skills through LangBot's existing `/api/v1/skills`
  surface.
- Activated Skills still use LangBot's existing sandbox and permission checks.

The missing layer is the product workflow before registration: deciding what is
worth keeping, generating a structured draft, scanning for secrets and
environment coupling, recording review/eval evidence, and exporting a package
that can then be registered through the normal runtime path.

## Auto Deposition Mode

Auto deposition is intended for a personal assistant that should learn from a
user-approved conversation or repeated workflow with one action. When enabled,
the Page `One-click Deposit` action and the `skill_auto_deposit` tool will:

1. Create a candidate from the provided evidence.
2. Generate a structured Skill draft.
3. Run deterministic risk scanning.
4. Apply the configured risk policy.
5. Automatically record an approval and export the package when allowed.

The mode still does not directly publish into the runtime registry. The result
contains a `register_skill_hint` so the assistant can write the package under
`/workspace/<skill-name>` and call LangBot's built-in `register_skill` tool.

The plugin can also learn passively from completed LangBot turns. When both
`auto_deposition_enabled` and `post_response_candidate_enabled` are enabled, an
EventListener watches `NormalMessageResponded`, reads the current
`user_message_text`, assistant `response_text`, function names, and available
query vars, then creates a candidate only when deterministic confidence is high
or the user explicitly says things like "沉淀一下", "记住这个流程", or "make
this a skill".

Post-response extraction is conservative:

- default off, even when the plugin is installed
- private/personal-assistant sessions only by default
- candidate-only by default
- optional auto-export still obeys `auto_deposition_policy`
- no automatic runtime `register_skill`
- no automatic LongTermMemory write

Post-response config:

- `post_response_candidate_enabled`: enables candidate creation after normal
  replies, default `false`.
- `post_response_auto_export`: approve and export low-risk candidates
  automatically, default `false`.
- `post_response_private_only`: restrict to private chats, default `true`.
- `post_response_min_confidence`: deterministic threshold, default `0.72`.
- `post_response_max_source_chars`: maximum copied turn text, default `6000`.
- `post_response_explicit_only`: require an explicit deposition phrase, default
  `false`.

The response includes explicit disclosures:

- Risks: over-generalizing one-off workflows, preserving private context,
  leaking secrets or local paths, and carrying prompt-injection text forward.
- Cost: source size, plugin storage writes, optional package export writes,
  runtime changes, and whether LLM calls were used. The current deterministic
  MVP uses zero LLM calls.

Config:

- `auto_deposition_enabled`: master switch, default `false`.
- `auto_deposition_policy`: `pass_only`, `allow_warn`, or `allow_blocked`.
- `auto_deposition_reviewer`: reviewer label for automatic approval records.
- `post_response_candidate_enabled`: post-response candidate extraction,
  default `false`.
- `post_response_auto_export`: automatic post-response review/export, default
  `false`.
- `retention_deprecate_score`: lifecycle score below which deprecation is recommended.
- `retention_archive_score`: lifecycle score below which archival is recommended.

## Lifecycle And Retention

Hermes-style learning needs provenance and recoverable forgetting, not just
writing. This plugin tracks a lightweight lifecycle for deposited Skill
candidates:

```text
candidate -> active -> deprecated -> archived
                  \-> superseded
```

Every candidate now carries provenance metadata:

- `origin`: `manual`, `auto_deposition`, `agent_review`, `imported`,
  `runtime_registered`, etc.
- `protected`: protected candidates cannot be deprecated, archived, or
  superseded unless an explicit operator action passes `force=true`.
- `auto_curation_eligible`: only agent/auto-created candidates are eligible for
  automatic lifecycle recommendations to be applied later.

Lifecycle events can be recorded through the `skill_lifecycle_manage` tool or
the Page API:

- positive signals: `used`, `success`, `positive_feedback`, `eval_pass`
- negative signals: `failure`, `negative_feedback`, `eval_fail`, `stale`,
  `security_issue`, `memory_conflict`, `superseded`

The retention evaluator computes a score and recommends `keep`, `deprecate`,
`archive`, or `superseded`. Reports include `auto_apply_allowed` so a future
curator can distinguish "safe to apply automatically" from "human review
needed". Applying an action only changes this plugin's governance record;
deleting or hiding a runtime Skill still needs LangBot's existing Skill
management path or a future admin proxy.

Exported packages include:

- `SKILL.md`
- `references/source-excerpt.md`
- `references/risk-report.json`
- `references/provenance.json`
- `references/learning-decision.json`
- `references/support-files.json`

This mirrors the Hermes pattern of keeping session-specific detail in support
files instead of flattening every one-off run into a narrow Skill.

## LongTermMemory Coordination

Use LongTermMemory and Skill Authoring as separate asset layers:

- LongTermMemory L1: stable profile facts and preferences.
- LongTermMemory L2: situational memories, decisions, events, and correction
  history.
- Skill Authoring: reusable procedures that need tools, sequencing, guardrails,
  and verification.

The `skill_lifecycle_manage` tool supports `memory_plan` for a candidate. It
classifies whether the source should primarily become a Skill, an L1 profile
update, an L2 episodic memory, or require manual review. When both apply, keep
the executable workflow as a Skill and store only a compact source or usage
summary in L2 memory.

The response includes a machine-readable `learning-decision/v1` object and
optional LongTermMemory tool suggestions. This plugin does not directly call
LongTermMemory; the agent or a future host-level workflow can apply the
suggested `update_profile` or `remember` call after user review.

When LongTermMemory is installed, its `_ltm_context` query var is preserved as
provenance summary for post-response candidates when available. That gives the
reviewer session/speaker context without coupling the two plugins or duplicating
memory writes.

## Hermes Parity Status

Implemented in this plugin:

- gated one-click deposition with risk/cost disclosure
- LangBot-native post-response candidate extraction from `NormalMessageResponded`
- provenance, protection, and auto-curation eligibility
- lifecycle scoring with recoverable archive/deprecate/supersede records
- export packages with support-file manifests
- shared learning decision output for LongTermMemory coordination

Not implemented inside this plugin:

- Hermes' post-turn background fork that reviews the full conversation
- prompt-cache-aware auxiliary model routing
- complete tool-result trace review beyond the current event/query vars
- direct runtime Skill archive/delete/restore
- automatic umbrella consolidation across all installed runtime Skills

Those need stable LangBot host APIs for richer run traces, cross-plugin calls,
runtime Skill provenance, and recoverable runtime archive/restore. They are not
required for the current LangBot-native candidate loop.

The pipeline refactor follow-up plan is documented in
[`docs/pipeline-host-integration-plan.md`](docs/pipeline-host-integration-plan.md).

## What Works In This MVP

- Page backend API for candidates, reviews, validation, and export.
- Admin-facing Page UI for drafting and reviewing candidates.
- LLM-callable tools:
  - `skill_auto_deposit`
  - `skill_lifecycle_manage`
  - `skill_candidate_create`
  - `skill_candidate_risk_check`
  - `skill_candidate_export`
- Deterministic `SKILL.md` generation with source refs and risk notes.
- Local plugin storage when running inside LangBot, with an in-memory fallback
  for tests and offline development.

## Repository Layout

```text
manifest.yaml
main.py
components/
  event_listener/
  pages/authoring/
  tools/
skill_authoring/
tests/
```

## Development

From this repository:

```bash
python -m pytest
```

Build with the LangBot plugin SDK CLI when available:

```bash
lbp build
```

Inside a LangBot run, an Agent can still create the final runtime Skill using
the built-in `register_skill` tool after writing the exported package under
`/workspace`. The Page backend can also be extended to call `/api/v1/skills`
with an admin API key when a deployment wants direct publishing from the review
screen.
