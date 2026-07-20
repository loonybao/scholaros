# Automation — keeping the data fresh

The pipeline is one command:

```
python -m compass run            # collect enabled sources -> analyze new/changed -> refresh
python -m compass run --skip-llm # same, but no LLM (no API spend) — the fallback
```

`run` does, in order:

1. **collect** every enabled source in `config/sources.yaml` (Aalto, Tampere,
   TU Delft; EURAXESS once you enable it) — official layer only, with the
   three-way discovery filter and change history.
2. **analyze** only opportunities whose analysis input changed (new posting, or
   the text/profile/prompt changed) — capped by `max_ai_items_per_run` and the
   daily cost limit. Skipped entirely with `--skip-llm`.
3. **refresh** — recompute derived (eligibility, timing, graduation horizon for
   *today*), rebuild the SQLite index, regenerate `vault/generated/`.

## Schedule it (run once)

```
powershell -ExecutionPolicy Bypass -File scripts\schedule_daily_run.ps1
```

Registers a daily Windows Scheduled Task ("ScholarOS Daily Run", default 07:00).
Options:

```
... schedule_daily_run.ps1 -Time 08:30     # different time
... schedule_daily_run.ps1 -Full           # include LLM analysis (needs API, see below)
... schedule_daily_run.ps1 -Remove         # unschedule
```

After each run, status shows on the **Data Health** page (and
`data/status/collector_health.json`). Collector failures are fail-soft — one
broken source never blocks the others — and the last error surfaces there.

## Turning on automatic analysis (needs an API)

Live analysis is **off until you provide a cheap OpenAI-compatible endpoint**.
The whole pipeline is built and tested — it just needs credentials:

1. `config/models.yaml` already sets `api.model` (01tree `gpt-5.4-mini`) and the
   per-1M input/output prices that drive the daily **$ cost cap**. Change the
   model there if you want a different one.
2. Copy `.env.example` to `.env` and fill in `COMPASS_API_KEY` (and
   `COMPASS_API_BASE_URL`, already pre-filled to the 01tree endpoint). `.env` is
   gitignored — the key is never committed. Never paste the key into chat.
3. Verify: `python -m compass check-llm` (one tiny call; prints OK + est. cost,
   never the key).
4. Analyse the backlog: `python -m compass analyze` (only new/changed items;
   capped by `max_ai_items_per_run` and the daily $ cap).
5. Re-run the scheduler with `-Full` for automatic daily analysis.

For 01tree specifically: use the OpenAI-compatible endpoint
`https://01tree.ai/codex/v1` (already in `.env.example`), not the `/claudecode`
one — this project speaks the OpenAI Chat Completions format. Check spend at
your 01tree USD balance page; the local estimate is in
`data/status/llm_usage.json`.

Safety rails (always on): only whitelisted content is ever sent (posting text +
your skill/domain summary + taxonomy — never `vault/notes`, the full CV, letters
or correspondence); a hard per-run item cap; and, with a price set, a daily cost
cap. A proposal is never auto-finalised regardless of source.
