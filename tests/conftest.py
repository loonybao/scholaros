from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from compass.config import Config, Paths
from compass.models import (
    Opportunity,
    OpportunityOfficial,
    Organisation,
    OrganisationOfficial,
)
from compass.store import Store

TODAY = date(2026, 7, 17)
RETRIEVED = datetime(2026, 7, 17, tzinfo=timezone.utc)


@pytest.fixture
def tmp_paths(tmp_path: Path) -> Paths:
    root = tmp_path
    (root / "config").mkdir()
    paths = Paths.from_root(root)
    for p in (paths.canonical, paths.evidence, paths.raw, paths.index, paths.status,
              paths.vault_generated, paths.vault_notes):
        p.mkdir(parents=True, exist_ok=True)
    return paths


@pytest.fixture
def store(tmp_paths: Paths) -> Store:
    return Store(tmp_paths.canonical, tmp_paths.lock_file)


@pytest.fixture
def cfg(tmp_paths: Paths) -> Config:
    return Config(
        paths=tmp_paths,
        constraints={
            "geography": {
                "allowed_regions": ["Europe"],
                "preferred_countries": ["Finland", "Netherlands"],
                "excluded_countries": [],
            },
            "languages": ["English"],
            "excluded_language_requirements": [],
            "requires_funding": True,
            "restricted_position_eligibility": None,
        },
    )


def make_opportunity(
    opp_id: str = "opp_test",
    title: str = "Doctoral Researcher in Human-Centred XR",
    org_id: str = "org_test_university",
    url: str = "https://example.org/jobs/1",
    deadline: date | None = date(2026, 8, 3),
    **official_overrides,
) -> Opportunity:
    official = dict(
        title=title,
        org_id=org_id,
        source="manual",
        canonical_url=url,
        retrieved_at=RETRIEVED,
        deadline=deadline,
        location="Tampere, Finland",
        language_requirements=["English"],
        status="open",
        funding="salaried",
        description_text="A test position.",
    )
    official.update(official_overrides)
    return Opportunity(id=opp_id, official=OpportunityOfficial(**official))


def make_organisation(org_id: str = "org_test_university") -> Organisation:
    return Organisation(
        id=org_id,
        official=OrganisationOfficial(
            name="Test University", org_type="university", country="Finland"
        ),
    )
