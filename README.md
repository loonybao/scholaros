# ScholarOS — Research Compass

Personal research career intelligence system: tracks funded European PhD / research
positions (priority: Aalto University, TU Delft), evaluates fit against my research
profile, and drives application decisions.

Core loop: **Signal → Evidence → Interpretation → Decision → Action → Outcome**.

## Architecture

| Layer | Technology |
|---|---|
| Canonical data | JSON files in `data/canonical/` (git-versioned source of truth) |
| Evidence | Cleaned source evidence in `data/evidence/` (raw HTML gitignored) |
| Query index | SQLite (`data/index/`, derived, rebuildable) |
| Web dashboard | FastAPI + no-build vanilla JS (`compass serve`, localhost only) |
| Notes & reading | Obsidian vault: `vault/generated/` (machine) + `vault/notes/` (human-only) |
| Semantic analysis | OpenAI-compatible API (configurable base_url; facts never come from AI) |

See `CLAUDE.md` for the system rules (field-layer ownership, write boundaries,
LLM context whitelist).

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
copy .env.example .env   # then fill in API credentials (needed from S4 on)
```

Open `vault/` in Obsidian ("Open folder as vault"). Your own notes go in
`vault/notes/` — automation never touches that folder.

## Commands

```
python -m compass new <type> --from-file stub.yaml   # manual entry (opportunity/organisation/person/...)
python -m compass validate                            # pydantic-check every canonical file
python -m compass export                              # regenerate vault/generated/
python -m compass migrate                             # apply schema migrations
python -m compass status                              # counts, review queue, collector health
python -m compass collect [--source aalto|tampere]    # (S3+) scrape official sources
python -m compass analyze                             # (S4+) LLM analysis of new/changed records
python -m compass decide                              # (S4+) rule-based decision proposals
python -m compass serve                               # (S2+) web dashboard at http://127.0.0.1:8000
python -m compass run                                 # full pipeline
```

## Daily workflow (target state)

1. Scheduled `compass run` collects, analyzes new/changed records within a hard
   daily budget, and regenerates both views.
2. Open the dashboard: Action Required, deadlines, review queue.
3. Finalize decisions (apply is never auto-finalized), work the actions, log
   outcomes in applications.
