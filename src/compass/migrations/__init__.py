"""Schema migrations for canonical JSON records.

Each migration module defines:
    VERSION: int          # the schema_version it upgrades records TO
    def migrate(record: dict) -> dict

`run_migrations` walks every canonical file and applies, in order, all
migrations with VERSION greater than the record's current schema_version.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Callable

Migration = tuple[int, Callable[[dict], dict]]


def load_migrations() -> list[Migration]:
    migrations: list[Migration] = []
    for mod_info in pkgutil.iter_modules(__path__):
        # migration modules are named m<version>_<slug>, e.g. m001_initial
        if not (mod_info.name.startswith("m") and mod_info.name[1:2].isdigit()):
            continue
        mod = importlib.import_module(f"{__name__}.{mod_info.name}")
        migrations.append((mod.VERSION, mod.migrate))
    return sorted(migrations, key=lambda m: m[0])


def upgrade_record(record: dict, migrations: list[Migration] | None = None) -> tuple[dict, bool]:
    """Return (record, changed). Applies pending migrations in version order."""
    if migrations is None:
        migrations = load_migrations()
    changed = False
    current = record.get("schema_version", 0)
    for version, fn in migrations:
        if version > current:
            record = fn(record)
            record["schema_version"] = version
            current = version
            changed = True
    return record, changed
