"""S5a closure: deterministic triage of unanalysed TU Delft records.

Classifies by title/faculty/evidence keyword rules (triage-v1) into
likely_relevant / possible_adjacent / low_priority. Nothing is deleted or
rejected here — the result is written to data/status/tudelft_triage.json for
audit, and deep analysis is performed only on the first two classes.

Run: .venv/Scripts/python.exe scripts/triage_s5a_tudelft.py
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from compass.config import Config
from compass.store import Store

TRIAGE_RULE_VERSION = "triage-v1"

# Title/evidence signals, checked in order (first match wins).
LIKELY = re.compile(
    r"\bxr\b|extended reality|virtual reality|augmented reality|mixed reality|"
    r"human.computer|human.centred|human.centered|human.technology|\bhci\b|"
    r"user.cent(er|re)d|user stud|haptic|interaction design",
    re.IGNORECASE,
)
ADJACENT = re.compile(
    r"\bdesign\b|behaviou?r|cognitive|user|wearable|mobile computing|"
    r"sensing.*(human|body|oral)|intra.oral|learning|education|training|"
    r"accessibilit|inclusi|experience",
    re.IGNORECASE,
)
# Faculty signal: Industrial Design Engineering is a design-research faculty.
ADJACENT_FACULTY = re.compile(r"industrial design", re.IGNORECASE)


def triage(title: str, faculty: str | None, description: str) -> tuple[str, str]:
    if LIKELY.search(title):
        return "likely_relevant", "title matches XR/HCI/user-research keywords"
    if faculty and ADJACENT_FACULTY.search(faculty):
        return "possible_adjacent", "hosted by a design-research faculty (IDE)"
    if ADJACENT.search(title):
        return "possible_adjacent", "title matches design/behaviour/user-adjacent keywords"
    # Description check: only strong LIKELY signals escalate from text alone.
    if LIKELY.search(description[:4000]):
        return "possible_adjacent", "description mentions XR/HCI-family keywords"
    return "low_priority", "no human-centred or design-research signals"


def main() -> None:
    cfg = Config.load()
    store = Store(cfg.paths.canonical, cfg.paths.lock_file)
    results = []
    counts = {"likely_relevant": 0, "possible_adjacent": 0, "low_priority": 0}

    for opp in store.load_all("opportunity"):
        if opp.official.source != "tudelft" or opp.ai is not None:
            continue
        org = None
        if opp.official.lab_org_id and store.exists("organisation", opp.official.lab_org_id):
            org = store.load("organisation", opp.official.lab_org_id).official.name
        category, reason = triage(
            opp.official.title, org, opp.official.description_text
        )
        counts[category] += 1
        results.append(
            {
                "id": opp.id,
                "native_id": opp.official.source_native_id,
                "title": opp.official.title,
                "faculty": org,
                "deadline": opp.official.deadline.isoformat()
                if opp.official.deadline else None,
                "category": category,
                "reason": reason,
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rule_version": TRIAGE_RULE_VERSION,
        "counts": counts,
        "records": sorted(results, key=lambda r: (r["category"], r["deadline"] or "9999")),
    }
    out = cfg.paths.status / "tudelft_triage.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"triage ({TRIAGE_RULE_VERSION}): {counts}")
    for r in payload["records"]:
        if r["category"] != "low_priority":
            print(f"  {r['category']:<17} {r['deadline'] or '----------'} {r['title'][:70]}")


if __name__ == "__main__":
    main()
