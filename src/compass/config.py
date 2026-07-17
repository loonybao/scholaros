"""Load and hold all project configuration (YAML + .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from `start` (or this file) until a directory with config/ is found."""
    p = (start or Path(__file__)).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / "config").is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate
    raise FileNotFoundError("Could not locate project root (config/ + pyproject.toml)")


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Paths:
    root: Path
    config: Path
    canonical: Path
    evidence: Path
    raw: Path
    index: Path
    status: Path
    vault_generated: Path
    vault_notes: Path
    lock_file: Path

    @classmethod
    def from_root(cls, root: Path) -> "Paths":
        data = root / "data"
        return cls(
            root=root,
            config=root / "config",
            canonical=data / "canonical",
            evidence=data / "evidence",
            raw=data / "raw",
            index=data / "index",
            status=data / "status",
            vault_generated=root / "vault" / "generated",
            vault_notes=root / "vault" / "notes",
            lock_file=data / ".compass.lock",
        )


@dataclass
class Config:
    paths: Paths
    profile: dict[str, Any] = field(default_factory=dict)
    target_identity: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, Any] = field(default_factory=dict)
    taxonomy: dict[str, Any] = field(default_factory=dict)
    models: dict[str, Any] = field(default_factory=dict)

    api_key: str | None = None
    api_base_url: str | None = None

    @classmethod
    def load(cls, root: Path | None = None) -> "Config":
        root = root or find_project_root()
        load_dotenv(root / ".env")
        paths = Paths.from_root(root)
        cfg = cls(
            paths=paths,
            profile=_load_yaml(paths.config / "current_profile.yaml"),
            target_identity=_load_yaml(paths.config / "target_identity.yaml"),
            constraints=_load_yaml(paths.config / "constraints.yaml"),
            sources=_load_yaml(paths.config / "sources.yaml"),
            taxonomy=_load_yaml(paths.config / "taxonomy.yaml"),
            models=_load_yaml(paths.config / "models.yaml"),
            api_key=os.environ.get("COMPASS_API_KEY") or None,
            api_base_url=os.environ.get("COMPASS_API_BASE_URL") or None,
        )
        return cfg

    def taxonomy_ids(self) -> set[str]:
        ids: set[str] = set()
        for group in self.taxonomy.values():
            if isinstance(group, list):
                for entry in group:
                    if isinstance(entry, dict) and "id" in entry:
                        ids.add(entry["id"])
        return ids
