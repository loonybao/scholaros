"""Canonical JSON store: the ONLY write path for data/canonical/.

Guarantees:
- Cross-process project lock (filelock) around every write.
- Atomic file replacement (temp file + os.replace).
- Every save appends a ChangeEntry with the actor and changed fields.
- Opportunity identity resolution: source_native_id -> canonical_url ->
  fingerprint(org_id, normalized_title, location, posted_date). Deadline is
  NOT part of identity; deadline changes update the existing record.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from filelock import FileLock

from .models import (
    ENTITY_DIRS,
    ENTITY_MODELS,
    ChangeEntry,
    Envelope,
    Opportunity,
    utcnow,
)

_ID_SAFE = re.compile(r"[^a-z0-9_-]+")


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = _ID_SAFE.sub("-", text.lower()).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return text[:max_len].rstrip("-")


def normalize_title(title: str) -> str:
    title = title.replace("–", "-").replace("—", "-")  # en/em dash
    return re.sub(r"\s+", " ", title.strip().lower())


# Query params that never contribute to identity (session/tracking/language).
_IGNORED_QUERY_PARAMS = {"rspvt", "lang", "utm_source", "utm_medium", "utm_campaign"}


def normalize_url(url: str) -> str:
    """Canonicalize a URL for identity comparison: lowercase host, sorted
    query params, tracking/session params dropped, no fragment."""
    parts = urlparse(url.strip())
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _IGNORED_QUERY_PARAMS
    )
    return urlunparse((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/") or "/",
        "",
        urlencode(query),
        "",
    ))


class Store:
    def __init__(self, canonical_dir: Path, lock_file: Path):
        self.canonical_dir = Path(canonical_dir)
        self._lock = FileLock(str(lock_file), timeout=30)
        lock_file.parent.mkdir(parents=True, exist_ok=True)

    def lock(self) -> FileLock:
        """Cross-process project lock. FileLock is reentrant, so callers may
        wrap check-then-save sequences (e.g. identity lookup + save) to make
        them atomic across processes."""
        return self._lock

    # ------------------------------------------------------------------ paths

    def _dir_for(self, entity_type: str) -> Path:
        return self.canonical_dir / ENTITY_DIRS[entity_type]

    def path_for(self, entity_type: str, entity_id: str) -> Path:
        return self._dir_for(entity_type) / f"{entity_id}.json"

    # ------------------------------------------------------------------- read

    def load(self, entity_type: str, entity_id: str) -> Envelope:
        path = self.path_for(entity_type, entity_id)
        model = ENTITY_MODELS[entity_type]
        with open(path, encoding="utf-8") as f:
            return model.model_validate_json(f.read())

    def load_all(self, entity_type: str) -> Iterator[Envelope]:
        d = self._dir_for(entity_type)
        if not d.is_dir():
            return
        model = ENTITY_MODELS[entity_type]
        for path in sorted(d.glob("*.json")):
            with open(path, encoding="utf-8") as f:
                yield model.model_validate_json(f.read())

    def exists(self, entity_type: str, entity_id: str) -> bool:
        return self.path_for(entity_type, entity_id).is_file()

    def iter_raw_files(self) -> Iterator[Path]:
        for sub in ENTITY_DIRS.values():
            d = self.canonical_dir / sub
            if d.is_dir():
                yield from sorted(d.glob("*.json"))

    # ------------------------------------------------------------------ write

    def save(self, entity: Envelope, actor: str, note: str | None = None) -> Envelope:
        """Persist an entity, appending a change-history entry.

        Computes fields_changed by diffing against the existing file (top-level
        layer.field granularity).
        """
        with self._lock:
            path = self.path_for(entity.entity_type, entity.id)
            fields_changed: list[str]
            if path.is_file():
                old = self.load(entity.entity_type, entity.id)
                fields_changed = _diff_fields(
                    old.model_dump(mode="json"), entity.model_dump(mode="json")
                )
                if not fields_changed:
                    return old  # nothing to write
            else:
                fields_changed = ["*created*"]

            entity.updated_at = utcnow()
            entity.change_history.append(
                ChangeEntry(
                    ts=entity.updated_at,
                    actor=actor,
                    fields_changed=fields_changed,
                    note=note,
                )
            )
            self._atomic_write(path, entity.model_dump_json(indent=2))
            return entity

    def write_raw(self, path: Path, content: str) -> None:
        """Locked atomic write for maintenance flows (migrations) that must
        bypass model round-tripping but still honor the locking contract."""
        with self._lock:
            self._atomic_write(path, content)

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.write("\n")
        os.replace(tmp, path)

    # ----------------------------------------------------- opportunity identity

    def find_opportunity(
        self,
        source_native_id: Optional[str],
        canonical_url: Optional[str],
        org_id: Optional[str] = None,
        title: Optional[str] = None,
        location: Optional[str] = None,
        posted_date: Optional[str] = None,
    ) -> Optional[Opportunity]:
        """Resolve opportunity identity. Deadline is deliberately NOT considered."""
        candidates = list(self.load_all("opportunity"))
        if source_native_id:
            for opp in candidates:
                if opp.official.source_native_id == source_native_id:
                    return opp
        if canonical_url:
            target = normalize_url(canonical_url)
            for opp in candidates:
                if normalize_url(opp.official.canonical_url) == target:
                    return opp
        if org_id and title:
            fp = (org_id, normalize_title(title), location or "", posted_date or "")
            for opp in candidates:
                o = opp.official
                # A candidate whose native id is known and DIFFERENT can never
                # be the same posting, even if the fingerprint collides (two
                # generic titles like "Postdoctoral Research Fellow" posted the
                # same day are distinct positions).
                if (
                    source_native_id
                    and o.source_native_id
                    and o.source_native_id != source_native_id
                ):
                    continue
                cand_fp = (
                    o.org_id,
                    normalize_title(o.title),
                    o.location or "",
                    o.posted_date.isoformat() if o.posted_date else "",
                )
                if cand_fp == fp:
                    return opp
        return None

    def new_id(self, entity_type: str, hint: str) -> str:
        from .models import ID_PREFIXES

        base = ID_PREFIXES[entity_type] + slugify(hint)
        candidate, n = base, 2
        while self.exists(entity_type, candidate):
            candidate = f"{base}-{n}"
            n += 1
        return candidate


def _diff_fields(old: dict, new: dict, prefix: str = "", depth: int = 0) -> list[str]:
    """Top-two-level diff: 'official.deadline', 'manual.notes', ..."""
    skip = {"updated_at", "change_history"}
    changed: list[str] = []
    keys = set(old) | set(new)
    for key in sorted(keys):
        if key in skip:
            continue
        ov, nv = old.get(key), new.get(key)
        if ov == nv:
            continue
        label = f"{prefix}{key}"
        if depth == 0 and (isinstance(ov, dict) or isinstance(nv, dict)):
            # Treat a missing/None layer as {} so adding e.g. the ai layer
            # records 'ai.summary', 'ai.fit_type', ... not just 'ai'.
            changed.extend(
                _diff_fields(ov or {}, nv or {}, prefix=f"{label}.", depth=1)
            )
        else:
            changed.append(label)
    return changed
