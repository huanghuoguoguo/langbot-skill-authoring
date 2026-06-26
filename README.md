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

## What Works In This MVP

- Page backend API for candidates, reviews, validation, and export.
- Admin-facing Page UI for drafting and reviewing candidates.
- LLM-callable tools:
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
