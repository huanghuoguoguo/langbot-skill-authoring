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
source evidence -> auto candidate -> risk report -> policy gate -> auto review/export
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

The response includes explicit disclosures:

- Risks: over-generalizing one-off workflows, preserving private context,
  leaking secrets or local paths, and carrying prompt-injection text forward.
- Cost: source size, storage writes, runtime changes, and whether LLM calls were
  used. The current deterministic MVP uses zero LLM calls.

Config:

- `auto_deposition_enabled`: master switch, default `false`.
- `auto_deposition_policy`: `pass_only`, `allow_warn`, or `allow_blocked`.
- `auto_deposition_reviewer`: reviewer label for automatic approval records.

## What Works In This MVP

- Page backend API for candidates, reviews, validation, and export.
- Admin-facing Page UI for drafting and reviewing candidates.
- LLM-callable tools:
  - `skill_auto_deposit`
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
