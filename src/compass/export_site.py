"""Static read-only dashboard for GitHub Pages.

Renders one self-contained HTML file (inline CSS, no JS, mobile-friendly) from
the same derived data the web app serves — so it can be viewed on any device
without running the server. Read-only by nature: interactive edits (create
application, change status) still happen in the local web app. Output goes to
site/ (or a given dir); every write is asserted to stay under that dir.
"""

from __future__ import annotations

import html
from datetime import date
from pathlib import Path

from .config import Config
from .index import browse_opportunities, dashboard_data
from .store import Store

# Plain-language labels mirroring the web UI (raw enums are never shown).
_REC = {"apply": "Worth applying", "consider": "Worth a look",
        "monitor": "Monitor", "reject": "Not pursuing"}
_TIMING = {"actionable_now": "Act now", "prepare_for_current_cycle": "Prepare now",
           "future_target": "Future target", "timing_mismatch": "Starts too early",
           "timing_unknown": "Start date unknown"}
_GATE = {"pass": "Eligible", "uncertain": "Confirm eligibility", "fail": "Not eligible"}
_FIT = {"exact-fit": "Exact fit", "adjacent-methodological-fit": "Adjacent fit",
        "poor-fit": "Poor fit"}
_TONE = {  # css class per recommendation
    "apply": "good", "consider": "info", "monitor": "neutral", "reject": "muted"}

_CSS = """
:root{--bg:#f4f2ee;--card:#fff;--ink:#1a2740;--ink2:#5b6472;--muted:#8a8f99;
--line:#e7e3db;--accent:#2f62c4;--good:#2f8f57;--warn:#a8710f;--info:#2f62c4;}
@media(prefers-color-scheme:dark){:root{--bg:#17181c;--card:#202228;--ink:#e9ebf0;
--ink2:#a6adba;--muted:#7e8595;--line:#2c2f37;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 system-ui,-apple-system,"Segoe UI","Noto Sans",sans-serif;padding:0 0 48px}
.wrap{max-width:900px;margin:0 auto;padding:18px}
h1{font-size:22px;margin:6px 0}h2{font-size:13px;text-transform:uppercase;
letter-spacing:.05em;color:var(--ink2);margin:26px 0 10px}
.sub{color:var(--ink2);font-size:13px;margin:0 0 4px}
.hero{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-top:12px}
.phase{font-size:20px;font-weight:700}.gen{color:var(--muted);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin-bottom:12px}
.card h3{margin:0 0 4px;font-size:15px}.card h3 a{color:var(--ink);text-decoration:none}
.org{color:var(--ink2);font-size:12.5px;margin-bottom:8px}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
.b{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:600;border:1px solid transparent}
.b.good{color:var(--good);background:rgba(47,143,87,.13)}
.b.info{color:var(--info);background:rgba(47,98,196,.12)}
.b.warn{color:var(--warn);background:rgba(200,140,30,.16)}
.b.neutral{color:var(--ink2);background:rgba(107,114,128,.12)}
.b.muted{color:var(--muted);background:rgba(107,114,128,.08)}
.meta{color:var(--ink2);font-size:12.5px}
.foot{color:var(--muted);font-size:12px;margin-top:28px;border-top:1px solid var(--line);padding-top:12px}
a{color:var(--accent)}
"""


def _b(text: str, tone: str = "neutral") -> str:
    return f'<span class="b {tone}">{html.escape(str(text))}</span>'


def _card(r: dict) -> str:
    rec = r.get("recommendation")
    gate = r.get("eligibility_gate")
    timing = r.get("timing_assessment")
    fit = r.get("fit_overall")
    org = html.escape((r.get("org_name") or r.get("org_id") or "").split(" (")[0])
    url = html.escape(r.get("canonical_url") or "")
    title = html.escape(r.get("title") or "")
    dl = r.get("deadline") or "no deadline"
    badges = []
    if rec:
        badges.append(_b(_REC.get(rec, rec), _TONE.get(rec, "neutral")))
    if gate:
        badges.append(_b(_GATE.get(gate, gate),
                         "good" if gate == "pass" else "warn" if gate == "uncertain" else "muted"))
    if timing:
        badges.append(_b(_TIMING.get(timing, timing),
                         "good" if timing in ("actionable_now", "prepare_for_current_cycle") else "info"))
    if fit is not None:
        badges.append(_b(f"fit {fit}", "info"))
    return (f'<div class="card"><h3>'
            + (f'<a href="{url}" target="_blank" rel="noopener">{title}</a>' if url else title)
            + f'</h3><div class="org">{org} · {html.escape(r.get("position_type") or "")}</div>'
            + f'<div class="badges">{"".join(badges)}</div>'
            + f'<div class="meta">Deadline: {html.escape(str(dl))} · {html.escape(r.get("location") or "")}</div>'
            + "</div>")


def render_html(cfg: Config, today: date | None = None) -> str:
    today = today or date.today()
    dash = dashboard_data(cfg, today)
    rows = browse_opportunities(cfg, {"scope": "relevant"})
    # rank: apply/consider first, then by fit
    order = {"apply": 0, "consider": 1, "monitor": 2, "reject": 3, None: 4}
    rows.sort(key=lambda r: (order.get(r.get("recommendation"), 4),
                             -(r.get("fit_overall") or 0)))

    h = dash.get("graduation_horizon") or {}
    parts = [f'<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<meta name="robots" content="noindex">',
             '<title>Research Compass</title>',
             f"<style>{_CSS}</style></head><body><div class='wrap'>",
             "<h1>Research Compass</h1>",
             f'<div class="gen">Updated {today.isoformat()} · read-only view · '
             "edit in the local app</div>"]

    if h:
        parts.append(
            f'<div class="hero"><div class="phase">{html.escape(h.get("phase_label",""))}</div>'
            f'<div class="sub">~{round(h.get("months_to_graduation",0))} months to expected MSc '
            f'completion ({html.escape(h.get("expected_graduation",""))}, '
            f'{html.escape(h.get("certainty",""))})</div>'
            f'<div class="meta" style="margin-top:8px">{html.escape(h.get("phase_guidance",""))}</div></div>')

    # action required
    ar = dash.get("action_required") or []
    tasks = dash.get("manual_tasks") or []
    if ar or tasks:
        parts.append("<h2>Action required</h2>")
        for t in tasks:
            parts.append(f'<div class="card"><h3>{html.escape(t.get("title",""))}</h3>'
                         f'<div class="meta">{html.escape(str(t.get("due_date") or ""))}</div></div>')
        for r in ar:
            parts.append(_card(r))

    parts.append(f"<h2>Relevant opportunities ({len(rows)})</h2>")
    if not rows:
        parts.append('<div class="card meta">Nothing relevant right now — the daily run will add new matches.</div>')
    for r in rows:
        parts.append(_card(r))

    parts.append('<div class="foot">Generated by ScholarOS / Research Compass. '
                 'This is a read-only snapshot; create applications and change '
                 'status in the local app. Data source: your private repository.</div>')
    parts.append("</div></body></html>")
    return "\n".join(parts)


def export_site(cfg: Config, out_dir: Path, today: date | None = None) -> Path:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    index = (out_dir / "index.html").resolve()
    if out_dir not in index.parents:
        raise RuntimeError(f"refusing to write outside {out_dir}: {index}")
    index.write_text(render_html(cfg, today), encoding="utf-8")
    # .nojekyll so GitHub Pages serves the file as-is (no Jekyll processing)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return index
