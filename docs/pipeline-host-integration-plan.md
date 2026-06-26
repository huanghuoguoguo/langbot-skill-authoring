# Pipeline Host Integration Plan

This document records two paths for moving Skill Authoring beyond
user-triggered deposition:

1. A LangBot-native candidate workflow that can use existing plugin events.
2. Host-side mechanisms needed later for full Hermes-like automatic learning.

Implementation of the full host loop is intentionally paused while LangBot's
pipeline refactor is in progress. The LangBot-native candidate loop described
below is implemented in the plugin and can be used before that refactor lands.

## Current Position

The plugin currently supports active, user- or agent-triggered deposition:

```text
evidence -> candidate -> risk scan -> review/export -> register_skill hint
```

It also supports a LangBot-native passive candidate loop:

```text
NormalMessageResponded
  -> query vars + assistant response + function names
  -> deterministic procedural-learning decision
  -> Skill Authoring candidate
  -> risk scan
  -> optional auto review/export
  -> register_skill hint only
```

It also records governance metadata that will be useful later:

- `provenance.origin`: `manual`, `auto_deposition`, `agent_review`,
  `imported`, `runtime_registered`, etc.
- `protected`: blocks archive/deprecate/supersede unless an explicit operator
  passes `force=true`.
- `auto_curation_eligible`: marks agent/auto-created candidates that a future
  curator may act on.
- `learning-decision/v1`: classifies a candidate as `skill`, `memory_l1`,
  `memory_l2`, or `manual_review`, and returns optional LongTermMemory tool
  suggestions.

This is enough for one-click deposition, reviewable Skill package export, and
post-response candidate creation. It is not yet the same as Hermes' automatic
background reviewer and runtime curator.

## Do Not Copy Hermes Mechanically

Hermes is useful as a reference for product behavior and safety invariants:

- separate memory from procedural Skills
- avoid one-session micro-Skills
- prefer candidates/review before durable mutation
- preserve provenance
- never auto-delete; only recoverable archive
- protect imported, marketplace, built-in, or user-owned assets
- disclose risk and cost

LangBot does not need to copy Hermes' implementation details. In particular,
LangBot does not need to fork a full background agent as the first step. A
plugin-first, candidate-only design fits LangBot better while the pipeline is
being refactored.

## LangBot-Native Candidate Loop

LongTermMemory already demonstrates the shape: it listens to
`NormalMessageResponded`, reads query vars and response text, extracts memory
candidates, and only auto-applies when explicitly configured. Skill Authoring
now follows the same plugin-native pattern for procedural Skill candidates.

Interim flow:

```text
NormalMessageResponded
  -> collect user_message_text / response_text / session identity
  -> classify whether the turn contains reusable procedural learning
  -> create a Skill Authoring candidate
  -> run deterministic risk scan
  -> optionally export package when config allows
  -> never auto-register runtime Skill in the first version
```

This does not require Hermes-style host parity. It uses the existing
EventListener surface plus conservative configuration.

Implemented config for this path:

- `auto_deposition_enabled`: existing master switch
- `post_response_candidate_enabled`: off by default
- `post_response_auto_export`: off by default
- `post_response_private_only`: on by default
- `post_response_max_source_chars`: bounded trace size
- `post_response_min_confidence`: threshold before creating a candidate
- `post_response_explicit_only`: require explicit user deposition phrase

Candidate source can include:

- user message text
- assistant response text
- session identity and speaker identity
- LongTermMemory `_ltm_context` query var, if available
- explicit user phrases such as "记住这个流程", "以后都这样做", "沉淀一下"

What it writes:

- a Skill Authoring candidate with `source_type=post_response`
- deterministic risk report
- provenance including event/query/session metadata
- `auto_curation_eligible=true`
- optional exported package when risk policy allows

What it deliberately does not do:

- no automatic runtime `register_skill`
- no automatic LongTermMemory `remember` or `update_profile`
- no automatic runtime Skill archive/restore
- no full background fork or auxiliary model call

Known limitations:

- tool-call traces may be incomplete or unavailable
- loaded Skill/runtime Skill usage may be invisible
- no host-enforced tool whitelist for a background agent
- no runtime Skill archive/restore API
- no automatic umbrella consolidation across installed runtime Skills

These limitations are acceptable for candidate creation and optional package
export. They are not acceptable for automatic runtime Skill mutation.

## Why Host Support Is Still Needed For Full Parity

Hermes gets its stronger behavior from the agent host, not only from a Skill
tool. After a turn, Hermes can fork a background reviewer with a snapshot of
the conversation, constrain its toolset to memory/skill management, and keep
the foreground conversation and prompt cache untouched. It also records runtime
Skill usage and runs a curator that archives, restores, and consolidates only
eligible Skills.

A LangBot plugin should not fake those guarantees locally when it starts
mutating runtime Skills automatically. The pipeline host needs to provide the
trace, execution boundary, runtime Skill lifecycle APIs, and cross-plugin
coordination surface for that later phase.

## Host Mechanisms For Full Parity

### 1. Post-Turn Trace Event

The pipeline should expose a stable post-turn event after model response and
tool execution are complete.

Minimum payload:

- `trace_id`, `query_id`, `session_id`, `bot_id`, `pipeline_id`
- launcher/session identity and current speaker identity
- user message, assistant response, tool calls, tool results, errors
- loaded/activated Skills and any runtime Skill registration events
- model/provider name, token/cost metadata if available
- timestamps and final turn status
- redaction metadata showing whether secrets or private fields were removed

The trace should be immutable for the review job. The review job should not
mutate the original conversation history.

### 2. Background Review Job

The host should support enqueueing an async post-turn learning review.

Required properties:

- non-blocking: user response is already delivered
- bounded: max input size, max runtime, max tool calls, max cost
- idempotent: repeated events for the same `trace_id` do not duplicate writes
- configurable model routing: main model, cheaper auxiliary model, or disabled
- cadence controls: every turn, every N turns, explicit user command, or off
- cancellation and failure reporting

The first version can run candidate extraction only. It does not need to
automatically register or archive runtime Skills.

### 3. Restricted Tool Execution Mode

Background learning should run in a restricted execution mode.

Allowed tools should be explicitly whitelisted, for example:

- Skill Authoring: candidate create, risk check, export, lifecycle
- LongTermMemory: candidate append or normal `remember` / `update_profile`
  only when policy allows

Blocked by default:

- shell/file mutation tools unrelated to the exported package
- direct runtime `register_skill` unless policy explicitly allows it
- admin/runtime Skill archive or restore unless running a curator job
- network tools unless the user requested source research

This restriction should be enforced by the host, not by prompt text alone.

### 4. Cross-Plugin Learning Decision Bus

Skill Authoring and LongTermMemory should coordinate through a small shared
event/schema rather than direct imports.

Current proposed schema:

```json
{
  "schema_version": "learning-decision/v1",
  "trace_id": "...",
  "candidate_id": "...",
  "asset_type": "skill | memory_l1 | memory_l2 | manual_review | none",
  "confidence": 0.0,
  "reason": "...",
  "risk_status": "pass | warn | blocked",
  "skill_action": "export_and_register | candidate_only | none",
  "memory_action": "update_profile | remember_episode | write_l2_summary_optional | none",
  "suggested_tool_calls": []
}
```

Host options:

- publish this as an internal plugin event
- let a workflow coordinator call both plugins
- persist decisions in a shared audit table

Skill Authoring should keep procedural workflows. LongTermMemory should keep
stable profile facts and episodic context. When both apply, keep the executable
steps in the Skill and store only a compact provenance/usage summary in L2.

### 5. Runtime Skill Governance API

Candidate lifecycle is not enough for Hermes-like behavior. The host also
needs runtime Skill governance APIs.

Minimum read API:

- list runtime Skills with name, path/package id, source, status
- provenance: user-created, agent-created, imported, marketplace, built-in
- `protected`, `pinned`, `auto_curation_eligible`
- use/view/activation counts and `last_used_at`
- linked candidate id or source trace id if known

Minimum write API:

- register/update a Skill package
- mark deprecated
- archive and restore
- pin and unpin
- dry-run lifecycle operations

Safety rules:

- no automatic hard delete
- archives must be recoverable
- marketplace/imported/built-in/protected Skills are not auto-archived
- destructive operations require audit records and operator-visible summaries

### 6. User Controls And Disclosure

Automatic learning must be opt-in and understandable.

Recommended configuration:

- master switch: off by default
- mode: `candidate_only`, `auto_export`, `auto_register`
- risk policy: `pass_only`, `allow_warn`, `allow_blocked`
- memory policy: `suggest_only`, `candidate_only`, `auto_apply_l1_l2`
- cadence: manual, every N turns, idle review
- model/cost budget: provider, model, max tokens, daily limit
- scope: private chats only, selected sessions, selected bots, or all

Every automatic run should disclose:

- what was reviewed
- what was written or proposed
- risk status
- estimated cost
- where to inspect, reject, restore, or archive the result

### 7. Audit, Observability, And UI

The host should expose a review log for learning jobs.

Useful fields:

- `trace_id`
- learning decision
- created candidates
- memory writes or memory candidates
- exported/registered Skill package ids
- runtime Skill lifecycle actions
- risk findings
- cost and duration
- reviewer model and policy

The UI should support:

- list pending learning candidates
- accept/reject Skill candidates
- accept/reject LongTermMemory candidates
- inspect archived/runtime Skills
- restore archived Skills
- pin protected Skills
- disable automatic learning for a scope

### 8. Security And Privacy

Host-side learning must treat traces as sensitive.

Required controls:

- secret scanning before any candidate or memory write
- redaction of credentials, tokens, local private paths when possible
- prompt-injection scan for text that would enter future prompts
- per-session and per-speaker isolation for group chats
- no learning from cron/system/background runs unless explicitly enabled
- no learning from private or admin-only traces across bot boundaries

## LongTermMemory Coordination

LongTermMemory already has most of the memory-side mechanics:

- L1 profile storage and injection
- L2 episodic recall
- candidate accept/reject workflow
- audit log
- episode status: active, superseded, archived
- consolidation preview/run

The missing piece is not another memory layer. The missing piece is a host
workflow that can take a post-turn trace, ask Skill Authoring for a learning
decision, then route memory-shaped decisions to LongTermMemory.

Recommended routing:

```text
stable preference/profile -> LongTermMemory L1
time-bound fact/event     -> LongTermMemory L2
tool/workflow procedure   -> Skill Authoring
both procedure + context  -> Skill + compact L2 provenance summary
uncertain/sensitive       -> candidate only, manual review
```

## Phased Plan

### Phase 0: LangBot-Native Candidate Extraction

Status: implemented.

- Optional EventListener for `NormalMessageResponded`.
- Reads user message, assistant response, session identity, function names, and
  available query vars.
- Creates Skill candidates only when procedural-learning confidence is high or
  the user explicitly asks to deposit the workflow.
- No runtime Skill mutation.
- No automatic memory writes.
- Default off; private/personal-assistant scopes are the first target.

### Phase 1: Passive Trace Capture After Pipeline Refactor

- Add or standardize a richer post-turn trace event.
- Include tool calls, tool results, loaded Skills, and runtime registration
  events when available.
- Let Skill Authoring create better candidates from richer traces.
- Still no runtime Skill mutation by default.

### Phase 2: Candidate-Only Background Review

- Add background learning job with restricted tools.
- Produce Skill candidates and LongTermMemory candidates.
- User reviews everything before it becomes durable runtime state.

### Phase 3: Auto Export For Low-Risk Skills

- Allow `auto_export` for pass/warn candidates depending on policy.
- Still require explicit `register_skill` or admin approval for runtime
  registration.
- Store `learning-decision/v1` and audit records.

### Phase 4: Runtime Skill Curator

- Add runtime usage telemetry and governance APIs.
- Implement stale/deprecate/archive recommendations.
- Allow recoverable auto-archive only for agent-created, unpinned,
  unprotected Skills.
- Add dry-run and restore UI before enabling automatic actions.

### Phase 5: Controlled Auto-Apply

- For personal assistant scopes only, allow automatic low-risk L1/L2 memory
  writes and Skill export.
- Keep runtime Skill registration and archive policy conservative.
- Enforce cost, privacy, and per-scope limits.

## Post-Refactor Evaluation Checklist

After the pipeline refactor lands, evaluate:

- Can plugins receive a complete post-turn trace without parsing logs?
- Can a plugin enqueue background work without blocking user response?
- Can background work run with a host-enforced tool whitelist?
- Is there a stable cross-plugin event/call mechanism?
- Can runtime Skills expose provenance, usage, pinned/protected state?
- Are archive/restore APIs recoverable and audited?
- Can learning be scoped per bot/session/speaker?
- Can users inspect and reject what automatic learning produced?
- Can cost and model routing be configured?
- Are secret and prompt-injection scans available before persistence?

If most answers are "yes", implement Phase 1 and Phase 2 first. Do not jump
directly to fully automatic runtime Skill mutation.

## Decision Rule

Use Hermes as the quality bar, not the implementation contract.

Prefer the LangBot-native path when the goal is:

- candidate creation
- one-click deposition
- personal-assistant scoped learning
- reviewable Skill package export
- LongTermMemory coordination

Require host parity mechanisms only when the goal is:

- automatic runtime Skill registration
- automatic runtime Skill archive/restore
- cross-session umbrella consolidation
- background jobs that execute tools without user supervision
- cost-sensitive model routing and execution isolation
