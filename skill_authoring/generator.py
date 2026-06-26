from __future__ import annotations

import re
import json
import textwrap
from typing import Any

import yaml

from .models import SkillCandidate, SkillDraft, SourceRef


SLUG_RE = re.compile(r"[^a-z0-9_-]+")
TOOL_NAMES = {"exec", "read", "write", "edit", "glob", "grep", "activate", "register_skill"}


def slugify(value: str, fallback: str = "learned-skill") -> str:
    slug = SLUG_RE.sub("-", value.strip().lower()).strip("-_")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        return fallback
    if slug[0].isdigit():
        slug = f"skill-{slug}"
    return slug[:64]


def compact_description(text: str, limit: int = 100) -> str:
    line = " ".join(text.strip().split())
    if not line:
        return "Reviewable workflow learned from LangBot evidence."
    if len(line) <= limit:
        return line
    return line[: limit - 1].rstrip() + "."


def infer_required_tools(text: str) -> list[str]:
    lowered = text.lower()
    tools = []
    for name in sorted(TOOL_NAMES):
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", lowered):
            tools.append(name)
    if "pytest" in lowered or "pnpm" in lowered or "uv " in lowered:
        if "exec" not in tools:
            tools.append("exec")
    return tools


def build_draft(
    *,
    title: str,
    source_text: str,
    source_ref: SourceRef,
    requested_name: str = "",
) -> SkillDraft:
    skill_name = slugify(requested_name or title or source_ref.title)
    display_name = title.strip() or skill_name.replace("-", " ").title()
    excerpt = source_text.strip()
    summary = compact_description(title or excerpt)
    procedure = _procedure_from_text(excerpt)
    return SkillDraft(
        name=skill_name,
        display_name=display_name,
        description=summary,
        when_to_use=(
            "Use this skill when a future LangBot task clearly matches the "
            f"source evidence: {summary}"
        ),
        when_not_to_use=(
            "Do not use this skill for one-off business context, unverified "
            "production changes, secrets handling, or tasks without similar evidence."
        ),
        procedure=procedure,
        pitfalls=(
            "Verify environment-specific paths, URLs, credentials, and versions before "
            "reusing this workflow. Do not assume source evidence is universally valid."
        ),
        verification=(
            "Run the linked QA case, reproduce the troubleshooting check, or execute the "
            "smallest relevant validation before considering the task complete."
        ),
        required_tools=infer_required_tools(excerpt),
        required_permissions=[],
    )


def _procedure_from_text(text: str) -> str:
    lines = [line.strip(" -\t") for line in text.splitlines() if line.strip()]
    if not lines:
        return "1. Inspect the source evidence.\n2. Apply the verified workflow.\n3. Record validation evidence."
    selected = lines[:8]
    return "\n".join(f"{index}. {line}" for index, line in enumerate(selected, start=1))


def render_skill_md(candidate: SkillCandidate) -> str:
    draft = candidate.draft
    metadata: dict[str, Any] = {
        "name": draft.name,
        "display_name": draft.display_name,
        "description": draft.description,
        "version": draft.version,
        "metadata": {
            "langbot": {
                "candidate_id": candidate.id,
                "source_refs": [candidate.source_ref.to_dict()],
                "required_tools": draft.required_tools,
                "risk_status": candidate.risk_report.status,
            }
        },
    }
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    body = f"""# {draft.display_name}

## When to Use
{draft.when_to_use.strip()}

## When Not to Use
{draft.when_not_to_use.strip()}

## Procedure
{draft.procedure.strip()}

## Pitfalls
{draft.pitfalls.strip()}

## Verification
{draft.verification.strip()}

## Source Notes
- Candidate: `{candidate.id}`
- Source: `{candidate.source_ref.type}:{candidate.source_ref.id}`
"""
    return f"---\n{frontmatter}\n---\n\n{textwrap.dedent(body).strip()}\n"


def export_package(candidate: SkillCandidate) -> dict[str, str]:
    return {
        "SKILL.md": render_skill_md(candidate),
        "references/source-excerpt.md": candidate.source_excerpt.strip() + "\n",
        "references/risk-report.json": json.dumps(
            candidate.risk_report.to_dict(),
            ensure_ascii=False,
            indent=2,
        ),
    }
