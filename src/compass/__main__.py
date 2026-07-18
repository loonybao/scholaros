"""CLI entry point: python -m compass <command>."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml
from pydantic import ValidationError

from .config import Config
from .models import ENTITY_DIRS, ENTITY_MODELS, utcnow
from .store import Store


def _make_store(cfg: Config) -> Store:
    return Store(cfg.paths.canonical, cfg.paths.lock_file)


# ----------------------------------------------------------------- commands #

def cmd_validate(cfg: Config, args: argparse.Namespace) -> int:
    store = _make_store(cfg)
    errors = 0
    checked = 0
    for path in store.iter_raw_files():
        entity_type = _entity_type_for(path)
        model = ENTITY_MODELS[entity_type]
        try:
            with open(path, encoding="utf-8") as f:
                model.model_validate_json(f.read())
            checked += 1
        except ValidationError as e:
            errors += 1
            print(f"INVALID {path}:\n{e}\n")
    print(f"validate: {checked} valid, {errors} invalid")
    return 1 if errors else 0


def cmd_migrate(cfg: Config, args: argparse.Namespace) -> int:
    from .migrations import load_migrations, upgrade_record

    store = _make_store(cfg)
    migrations = load_migrations()
    upgraded = 0
    for path in store.iter_raw_files():
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
        record, changed = upgrade_record(record, migrations)
        if changed:
            record.setdefault("change_history", []).append(
                {
                    "ts": utcnow().isoformat(),
                    "actor": "migration",
                    "fields_changed": ["schema_version"],
                    "note": f"migrated to v{record['schema_version']}",
                }
            )
            record["updated_at"] = utcnow().isoformat()
            store.write_raw(path, json.dumps(record, indent=2, ensure_ascii=False))
            upgraded += 1
    print(f"migrate: {upgraded} record(s) upgraded, latest schema version "
          f"{max((v for v, _ in migrations), default=0)}")
    return 0


def cmd_export(cfg: Config, args: argparse.Namespace) -> int:
    from .export_vault import VaultExporter

    store = _make_store(cfg)
    # Recompute derived layer before exporting so views are never stale.
    _recompute_all_derived(cfg, store)
    exporter = VaultExporter(cfg, store)
    count = exporter.export_all(date.today())
    print(f"export: {count} file(s) written to {cfg.paths.vault_generated}")
    return 0


def cmd_new(cfg: Config, args: argparse.Namespace) -> int:
    entity_type = args.type
    if entity_type not in ENTITY_MODELS:
        print(f"unknown entity type '{entity_type}'; one of {list(ENTITY_MODELS)}")
        return 2
    stub_path = Path(args.from_file)
    with open(stub_path, encoding="utf-8") as f:
        stub = yaml.safe_load(f)

    store = _make_store(cfg)
    if "id" not in stub:
        hint = args.id_hint or _default_hint(entity_type, stub)
        stub["id"] = store.new_id(entity_type, hint)
    stub.setdefault("entity_type", entity_type)

    model = ENTITY_MODELS[entity_type]
    try:
        entity = model.model_validate(stub)
    except ValidationError as e:
        print(f"stub failed validation:\n{e}")
        return 1

    # Identity check + save under one cross-process lock so two concurrent
    # `compass new` runs cannot both pass the check and create duplicates.
    with store.lock():
        if entity_type == "opportunity":
            existing = store.find_opportunity(
                entity.official.source_native_id,
                entity.official.canonical_url,
                entity.official.org_id,
                entity.official.title,
                entity.official.location,
                entity.official.posted_date.isoformat()
                if entity.official.posted_date
                else None,
            )
            if existing is not None and existing.id != entity.id:
                print(
                    f"refusing to create duplicate: identity matches existing "
                    f"'{existing.id}'. Update that record instead."
                )
                return 1

        store.save(entity, actor="manual", note=f"created from {stub_path.name}")
    print(f"created {entity_type} {entity.id}")
    return 0


def cmd_collect(cfg: Config, args: argparse.Namespace) -> int:
    from .collect import run_collectors

    store = _make_store(cfg)
    results = run_collectors(cfg, store, only_source=args.source)
    if not results:
        print("collect: no sources ran (enable them in config/sources.yaml "
              "or pass --source)")
        return 1
    failed = False
    for source, stats in results.items():
        if stats.error:
            failed = True
            print(f"{source}: FAILED — {stats.error}")
        else:
            print(f"{source}: {stats.fetched} listed, {stats.relevant} accepted, "
                  f"{stats.created} created, {stats.updated} updated, "
                  f"{stats.unchanged} unchanged, "
                  f"{stats.candidates} candidates (audited), "
                  f"{stats.skipped_irrelevant} irrelevant (audited)")
    _recompute_all_derived(cfg, store)
    print("derived layer recomputed; run `compass export` / `compass serve` to view")
    return 1 if failed else 0


def cmd_prepare_analysis(cfg: Config, args: argparse.Namespace) -> int:
    from .analysis_io import prepare_packet

    store = _make_store(cfg)
    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    packet = prepare_packet(cfg, store, ids)
    out = Path(args.out) if args.out else (
        cfg.paths.root / "data" / "analysis"
        / f"packet-{utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(packet, f, indent=2, ensure_ascii=False)
    print(f"prepare-analysis: {len(ids)} opportunity(ies) -> {out}")
    return 0


def cmd_import_analysis(cfg: Config, args: argparse.Namespace) -> int:
    from .analysis_io import import_results

    store = _make_store(cfg)
    report = import_results(cfg, store, Path(args.result_file), model=args.model)
    for opp_id in report["imported"]:
        print(f"imported: {opp_id}")
    for msg in report["rejected"]:
        print(f"REJECTED: {msg}")
    if report["imported"]:
        _recompute_all_derived(cfg, store)
        print("derived layer recomputed")
    print(f"import-analysis: {len(report['imported'])} imported, "
          f"{len(report['rejected'])} rejected")
    return 1 if report["rejected"] else 0


def cmd_analyze(cfg: Config, args: argparse.Namespace) -> int:
    from .analyze import analyze

    store = _make_store(cfg)
    report = analyze(cfg, store, limit=args.limit, skip_llm=args.skip_llm)
    print(f"analyze: {report['pending']} pending, {report['selected']} selected")
    if report.get("error"):
        print(f"  not run: {report['error']}")
    for opp_id in report["imported"]:
        print(f"  analyzed: {opp_id}")
    for msg in report["rejected"]:
        print(f"  REJECTED: {msg}")
    if report["imported"]:
        _recompute_all_derived(cfg, store)
        print(f"analyze: {len(report['imported'])} analyzed, "
              f"{len(report['rejected'])} rejected; derived recomputed "
              f"(run `compass export` / `serve` to view)")
    return 1 if report["rejected"] else 0


def cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    """Full production pipeline: collect -> analyze -> derived + index + vault.
    --skip-llm collects and refreshes without spending tokens (fallback)."""
    from .analyze import analyze
    from .collect import run_collectors
    from .views import refresh_all

    store = _make_store(cfg)
    failed = False

    results = run_collectors(cfg, store, only_source=args.source)
    if not results:
        print("run: no collectors ran (enable sources in config/sources.yaml)")
    for source, stats in results.items():
        if stats.error:
            failed = True
            print(f"collect {source}: FAILED — {stats.error}")
        else:
            print(f"collect {source}: {stats.created} created, {stats.updated} "
                  f"updated, {stats.unchanged} unchanged")

    report = analyze(cfg, store, limit=args.limit, skip_llm=args.skip_llm)
    note = f" (not run: {report['error']})" if report.get("error") else ""
    print(f"analyze: {report['selected']} selected, "
          f"{len(report['imported'])} analyzed, "
          f"{len(report['rejected'])} rejected{note}")

    refresh_all(cfg, store)
    print("run: derived recomputed, index rebuilt, vault regenerated")
    return 1 if failed or report["rejected"] else 0


def cmd_rebuild_index(cfg: Config, args: argparse.Namespace) -> int:
    from .index import rebuild_index

    store = _make_store(cfg)
    rows = rebuild_index(cfg, store)
    print(f"rebuild-index: {rows} row(s) indexed at {cfg.paths.index / 'compass.sqlite'}")
    return 0


def cmd_serve(cfg: Config, args: argparse.Namespace) -> int:
    from .web import serve

    # Refresh derived layer so the dashboard shows current urgency/gates.
    _recompute_all_derived(cfg, _make_store(cfg))
    print(f"Research Compass dashboard: http://127.0.0.1:{args.port}/  (Ctrl+C to stop)")
    serve(cfg, port=args.port)
    return 0


def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    store = _make_store(cfg)
    print("Research Compass status")
    print("-" * 40)
    total = 0
    for entity_type, subdir in ENTITY_DIRS.items():
        d = cfg.paths.canonical / subdir
        n = len(list(d.glob("*.json"))) if d.is_dir() else 0
        total += n
        print(f"{entity_type:<14} {n}")
    print("-" * 40)
    print(f"{'total':<14} {total}")

    review = [
        o.id for o in store.load_all("opportunity") if o.derived.needs_review
    ]
    print(f"\nmanual review queue: {len(review)}")
    for rid in review:
        print(f"  - {rid}")

    health_path = cfg.paths.status / "collector_health.json"
    if health_path.is_file():
        with open(health_path, encoding="utf-8") as f:
            health = json.load(f)
        print("\ncollector health:")
        for source, info in health.items():
            print(f"  {source}: last_success={info.get('last_success')}, "
                  f"errors={info.get('consecutive_errors', 0)}")
    else:
        print("\ncollector health: no collectors run yet")

    api_ready = bool(cfg.api_key and cfg.api_base_url and cfg.models.get("api", {}).get("model"))
    print(f"\nLLM configured: {'yes' if api_ready else 'no (fill .env + config/models.yaml for S4)'}")
    return 0


# ------------------------------------------------------------------ helpers #

def _entity_type_for(path: Path) -> str:
    subdir = path.parent.name
    for etype, d in ENTITY_DIRS.items():
        if d == subdir:
            return etype
    raise ValueError(f"unknown canonical subdir: {subdir}")


def _default_hint(entity_type: str, stub: dict) -> str:
    official = stub.get("official", {})
    return official.get("title") or official.get("name") or "record"


def _recompute_all_derived(cfg: Config, store: Store) -> None:
    # Rules only ever write the derived layer. official.status transitions
    # (e.g. open->closed) belong to collectors/manual entry; a passed deadline
    # already yields eligibility_gate=fail via the rules.
    from .rules import recompute_derived

    today = date.today()
    for opp in list(store.load_all("opportunity")):
        new_derived = recompute_derived(opp, cfg.constraints, today)
        if new_derived != opp.derived:
            opp.derived = new_derived
            store.save(opp, actor="rules", note="derived layer recomputed")


# --------------------------------------------------------------------- main #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compass", description="ScholarOS Research Compass")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="pydantic-check every canonical file")
    sub.add_parser("migrate", help="apply schema migrations to canonical files")
    sub.add_parser("export", help="regenerate vault/generated/")
    sub.add_parser("status", help="record counts, review queue, collector health")
    sub.add_parser("rebuild-index", help="rebuild the SQLite query index from canonical")

    p_collect = sub.add_parser("collect", help="run collectors against official sources")
    p_collect.add_argument("--source", help="run a single source regardless of enabled flag")

    p_prep = sub.add_parser(
        "prepare-analysis",
        help="export a whitelisted analysis packet for selected opportunities",
    )
    p_prep.add_argument("--ids", required=True, help="comma-separated opportunity ids")
    p_prep.add_argument("--out", help="output path (default data/analysis/packet-<ts>.json)")

    p_imp = sub.add_parser(
        "import-analysis",
        help="validate and import structured analysis results (ai layer only)",
    )
    p_imp.add_argument("result_file", help="JSON result file")
    p_imp.add_argument("--model", default="claude-fable-5",
                       help="model identifier recorded as provenance")

    p_analyze = sub.add_parser(
        "analyze", help="analyze new/changed opportunities via the configured LLM")
    p_analyze.add_argument("--limit", type=int, default=None,
                           help="max items this run (capped by config max_ai_items_per_run)")
    p_analyze.add_argument("--skip-llm", action="store_true",
                           help="report what would be analysed without calling the API")

    p_run = sub.add_parser(
        "run", help="full pipeline: collect -> analyze -> derived + index + vault")
    p_run.add_argument("--source", help="collect a single source")
    p_run.add_argument("--limit", type=int, default=None, help="max items to analyse")
    p_run.add_argument("--skip-llm", action="store_true",
                       help="collect + refresh only, no LLM spend (fallback)")

    p_serve = sub.add_parser("serve", help="run the local web app (127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8000)

    p_new = sub.add_parser("new", help="create an entity from a YAML stub file")
    p_new.add_argument("type", help=f"one of {list(ENTITY_MODELS)}")
    p_new.add_argument("--from-file", required=True, help="YAML stub path")
    p_new.add_argument("--id-hint", help="hint for ID generation (default: title/name)")

    args = parser.parse_args(argv)
    cfg = Config.load()

    commands = {
        "validate": cmd_validate,
        "migrate": cmd_migrate,
        "export": cmd_export,
        "new": cmd_new,
        "status": cmd_status,
        "rebuild-index": cmd_rebuild_index,
        "serve": cmd_serve,
        "collect": cmd_collect,
        "analyze": cmd_analyze,
        "run": cmd_run,
        "prepare-analysis": cmd_prepare_analysis,
        "import-analysis": cmd_import_analysis,
    }
    return commands[args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
