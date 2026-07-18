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

1. In `config/models.yaml` set `api.model` (e.g. `gpt-4o-mini`) and, optionally,
   `api.price_per_1k_tokens` to enable the daily **$ cost cap**.
2. In `.env` set `COMPASS_API_KEY` and `COMPASS_API_BASE_URL`.
3. Test once: `python -m compass analyze --limit 3`.
4. Re-run the scheduler with `-Full`.

Safety rails (always on): only whitelisted content is ever sent (posting text +
your skill/domain summary + taxonomy — never `vault/notes`, the full CV, letters
or correspondence); a hard per-run item cap; and, with a price set, a daily cost
cap. A proposal is never auto-finalised regardless of source.
