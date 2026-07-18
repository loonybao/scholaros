# ScholarOS / Research Compass — rules for AI assistants

Personal research career intelligence system. Canonical data = JSON files under
`data/canonical/`. SQLite and `vault/generated/` are derived and disposable.

## Write-permission boundaries (enforced in code, not just here)

Automation (collectors, analyze, export, web endpoints, any AI assistant) may write ONLY:

- `data/canonical/` — through `compass.store` (project lock + atomic replace), never by hand-editing JSON
- `data/evidence/`, `data/raw/`, `data/index/`, `data/status/`
- `vault/generated/` — via `compass.export_vault` only; the exporter asserts every
  output path resolves under `vault/generated/` and raises otherwise

`vault/notes/` is HUMAN-ONLY. No code path, tool call, or assistant edit may create,
modify, or delete anything under it. Ever.

## Field-layer ownership

- `official.*` — written only by collectors or manual entry, always with
  `source_url`, `retrieved_at`, and evidence references. Facts (deadline, salary,
  status, URLs) come from parsers or the human.
- `ai.*` — written only by the analyze stage; carries `model`, `prompt_version`,
  `confidence`, `analysis_input_hash`. The AI layer schema has NO fact fields;
  do not add any.
- `derived.*` — computed by `compass.rules`; always recomputable, never hand-edited.
- `manual.*` — written only by the human (CLI or dashboard forms). Automation must
  never modify it. Merges never cross layers.

## AI is not a fact source

LLM output that fails schema validation is discarded (one retry, then quarantine to
the manual-review queue with the raw response logged). Never "fix" invalid AI output
by hand into `official.*`. Unknown hard constraints stay null and force
`eligibility_gate=uncertain` + `needs_review=true` — do not invent defaults.
`decision=apply` is never auto-finalized.

## LLM context whitelist

Only whitelisted content may be sent to the configured API (see `config/models.yaml`):
opportunity/signal official text, taxonomy, and the skill/theme summary fields of the
profile. NEVER send: `vault/notes/`, the full private CV, recommendation letters,
private correspondence, or unpublished manuscript text.

## Identity & dedup

Opportunity identity excludes deadline. Priority: `source_native_id` →
`canonical_url` → fingerprint `(org_id, normalized_title, location, posted_date)`.
A deadline change updates the existing record and appends to `change_history`.

## Web write layer (S8a+)

The web UI may write ONLY manual-layer fields, Application records, Action
records, and user notes — through narrowly-scoped endpoints that go via
`compass.store` (actor="user", field-level change_history, atomic + locked).
Requests use Pydantic models with `extra="forbid"`; official/ai/derived fields
can never be smuggled in. Writes reject stale updates (optimistic concurrency
on `updated_at`), avoid no-op history, refresh the SQLite index and
`vault/generated/`, and never touch `vault/notes/`. Incorrect official data is
reported via a data-issue action for review, never edited in place.

Deferred decision (S8b): skill progress will become a canonical `SkillProgress`
(a.k.a. ProfileState) entity holding only the changing per-skill fields
(current_level, learning_status, confidence, target, evidence, notes). The
stable baseline stays in `config/current_profile.yaml`; the effective profile
is baseline + audited SkillProgress. Do NOT let the web edit
`current_profile.yaml` directly, and do NOT add editable skills in S8a.

## Conventions

- Every file open uses `encoding="utf-8"`; paths via `pathlib`.
- Generated markdown filenames = entity IDs (stable); links use IDs, never titles.
- Web server binds 127.0.0.1 by default; no LAN exposure without explicit auth config.
- Schema changes require a migration in `src/compass/migrations/` and a
  `schema_version` bump; run `python -m compass migrate`.
- Tests: collector changes update their HTML fixtures; exporter changes update golden
  files deliberately; no network access in tests.
- Verify with `python -m compass validate` and `pytest` before committing.
