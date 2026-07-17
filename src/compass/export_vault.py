"""Render canonical entities to Obsidian markdown under vault/generated/.

Safety: every output path is asserted to resolve under vault/generated/.
vault/notes/ is never touched. The generated tree is deleted and rebuilt on
every run — filenames are entity IDs so links from human notes stay stable.
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from .config import Config
from .models import Application, Opportunity, Organisation, Person, Signal
from .store import Store

SUBDIRS = {
    "opportunity": "01-Opportunities",
    "organisation": "02-Organisations",
    "person": "03-Researchers",
    "signal": "04-Signals",
    "application": "06-Applications",
}


class VaultExporter:
    def __init__(self, cfg: Config, store: Store):
        self.cfg = cfg
        self.store = store
        self.generated = cfg.paths.vault_generated.resolve()

    # ------------------------------------------------------------------ guard

    def _safe_path(self, *parts: str) -> Path:
        path = self.generated.joinpath(*parts).resolve()
        if self.generated not in path.parents and path != self.generated:
            raise RuntimeError(
                f"Export path escapes vault/generated/: {path}"
            )
        return path

    def _write(self, relpath: list[str], content: str) -> None:
        path = self._safe_path(*relpath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    # ------------------------------------------------------------------- main

    def export_all(self, today: date) -> int:
        # Refuse to operate through a symlink/junction: the guard's trusted
        # base must be the real vault/generated directory, never a redirect
        # (which could point delete/write operations at vault/notes).
        unresolved = self.cfg.paths.vault_generated
        if unresolved.exists() and (
            unresolved.is_symlink() or unresolved.resolve() != self.generated
        ):
            raise RuntimeError(
                f"vault/generated is a symlink/junction ({unresolved} -> "
                f"{unresolved.resolve()}); refusing to export"
            )
        notes = self.cfg.paths.vault_notes.resolve()
        if self.generated == notes or self.generated in notes.parents:
            raise RuntimeError("vault/generated resolves into vault/notes; refusing")

        if self.generated.exists():
            shutil.rmtree(self.generated)
        self.generated.mkdir(parents=True, exist_ok=True)
        # Ensure the human-only folder exists (created empty once, never
        # written into by any code path).
        self.cfg.paths.vault_notes.mkdir(parents=True, exist_ok=True)

        count = 0
        opportunities = list(self.store.load_all("opportunity"))
        organisations = {o.id: o for o in self.store.load_all("organisation")}
        people = list(self.store.load_all("person"))
        signals = list(self.store.load_all("signal"))
        applications = list(self.store.load_all("application"))

        for opp in opportunities:
            self._write(
                [SUBDIRS["opportunity"], f"{opp.id}.md"],
                self._render_opportunity(opp, organisations),
            )
            count += 1
        for org in organisations.values():
            self._write(
                [SUBDIRS["organisation"], f"{org.id}.md"], self._render_organisation(org)
            )
            count += 1
        for per in people:
            self._write(
                [SUBDIRS["person"], f"{per.id}.md"],
                self._render_person(per, organisations),
            )
            count += 1
        for sig in signals:
            self._write([SUBDIRS["signal"], f"{sig.id}.md"], self._render_signal(sig))
            count += 1
        for app in applications:
            self._write(
                [SUBDIRS["application"], f"{app.id}.md"], self._render_application(app)
            )
            count += 1

        self._write(
            ["00-Dashboard.md"],
            self._render_dashboard(opportunities, organisations, people, today),
        )
        count += 1
        return count

    # -------------------------------------------------------------- templates

    def _render_opportunity(
        self, opp: Opportunity, orgs: dict[str, Organisation]
    ) -> str:
        o, d, m = opp.official, opp.derived, opp.manual
        org_name = orgs[o.org_id].official.name if o.org_id in orgs else o.org_id
        lines = [
            "---",
            f"id: {opp.id}",
            "type: opportunity",
            f"title: \"{o.title}\"",
            f"organisation: \"{org_name}\"",
            f"deadline: {o.deadline or 'unknown'}",
            f"status: {o.status}",
            f"eligibility_gate: {d.eligibility_gate}",
            f"fit_overall: {d.fit_overall if d.fit_overall is not None else 'not-analyzed'}",
            f"urgency: {d.urgency}",
            f"needs_review: {str(d.needs_review).lower()}",
            "---",
            "",
            f"# {o.title}",
            "",
            f"**Organisation:** [[{o.org_id}]] ({org_name})",
            f"**Deadline:** {o.deadline or 'unknown'}"
            + (f" ({o.deadline_note})" if o.deadline_note else ""),
            f"**Location:** {o.location or 'unknown'}",
            f"**Position type:** {o.position_type}",
            f"**Salary:** {o.salary_text or 'not stated'}",
            f"**Duration:** {o.duration_text or 'not stated'}",
            f"**Status:** {o.status}",
            f"**Official source:** {o.canonical_url}",
            "",
            "## Eligibility",
            "",
            f"Gate: **{d.eligibility_gate}**"
            + (
                f" (days to deadline: {d.days_to_deadline})"
                if d.days_to_deadline is not None
                else ""
            ),
            "",
        ]
        for r in d.eligibility_reasons:
            lines.append(f"- {r}")
        lines += ["", "## Description", "", o.description_text or "_(no text saved)_", ""]

        if opp.ai:
            ai = opp.ai
            lines += [
                "## AI analysis",
                "",
                f"_{ai.model} · {ai.prompt_version} · confidence {ai.confidence:.2f}_",
                "",
                ai.summary,
                "",
                f"| Dimension | Score |",
                f"|---|---|",
                f"| Thematic fit | {ai.thematic_fit.score} |",
                f"| Methodological fit | {ai.methodological_fit.score} |",
                f"| Growth value | {ai.growth_value.score} |",
                f"| Strategic value | {ai.strategic_value.score} |",
                f"| **Overall** | **{d.fit_overall}** |",
                "",
                f"**Fit type:** {ai.fit_type}",
                "",
                "**Missing skills:** " + (", ".join(ai.missing_skills) or "none noted"),
                "",
            ]
            if ai.risks:
                lines.append("**Risks:**")
                lines += [f"- {r}" for r in ai.risks]
                lines.append("")
        else:
            lines += ["## AI analysis", "", "_Not analyzed yet._", ""]

        if m.notes or m.tags:
            lines += ["## Manual annotations (from record)", ""]
            if m.tags:
                lines.append("Tags: " + ", ".join(m.tags))
            if m.notes:
                lines.append(m.notes)
            lines.append("")

        lines += [
            "---",
            f"_Generated file — do not edit. Personal notes: create "
            f"`vault/notes/{opp.id}.md` and link [[{opp.id}]]._",
            "",
        ]
        return "\n".join(lines)

    def _render_organisation(self, org: Organisation) -> str:
        o, m = org.official, org.manual
        lines = [
            "---",
            f"id: {org.id}",
            "type: organisation",
            f"name: \"{o.name}\"",
            f"org_type: {o.org_type}",
            f"target: {str(m.target).lower()}",
            "---",
            "",
            f"# {o.name}",
            "",
            f"**Type:** {o.org_type}",
            f"**Country:** {o.country or 'unknown'}",
            f"**Website:** {o.website or 'unknown'}",
        ]
        if o.parent_org_id:
            lines.append(f"**Parent:** [[{o.parent_org_id}]]")
        if m.priority:
            lines.append(f"**Priority:** {m.priority}")
        lines += [
            "",
            "---",
            f"_Generated file — do not edit. Personal notes: `vault/notes/{org.id}.md`._",
            "",
        ]
        return "\n".join(lines)

    def _render_person(self, per: Person, orgs: dict[str, Organisation]) -> str:
        o, m = per.official, per.manual
        org_name = (
            orgs[o.org_id].official.name if o.org_id and o.org_id in orgs else o.org_id
        )
        lines = [
            "---",
            f"id: {per.id}",
            "type: person",
            f"name: \"{o.name}\"",
            f"contact_status: {m.contact_status}",
            "---",
            "",
            f"# {o.name}",
            "",
            f"**Title:** {o.title or 'unknown'}",
            f"**Organisation:** " + (f"[[{o.org_id}]] ({org_name})" if o.org_id else "unknown"),
            f"**Profile:** {o.profile_url or 'unknown'}",
            f"**Contact status:** {m.contact_status}",
            "",
        ]
        if per.ai:
            lines += [
                "## Alignment (AI)",
                "",
                per.ai.recent_work_summary,
                "",
                per.ai.alignment_notes,
                "",
            ]
        lines += [
            "---",
            f"_Generated file — do not edit. Personal notes: `vault/notes/{per.id}.md`._",
            "",
        ]
        return "\n".join(lines)

    def _render_signal(self, sig: Signal) -> str:
        o = sig.official
        lines = [
            "---",
            f"id: {sig.id}",
            "type: signal",
            f"signal_type: {o.signal_type}",
            "---",
            "",
            f"# {o.title}",
            "",
            f"**Type:** {o.signal_type}",
            f"**Published:** {o.published_at or 'unknown'}",
            f"**Source:** {o.url or o.source}",
            "",
            o.excerpt,
            "",
        ]
        if sig.ai:
            lines += [
                "## Triage (AI)",
                "",
                f"Relevance {sig.ai.relevance_score} · strength {sig.ai.strength}",
                "",
                sig.ai.implications,
                "",
            ]
        lines += ["---", "_Generated file — do not edit._", ""]
        return "\n".join(lines)

    def _render_application(self, app: Application) -> str:
        m = app.manual
        lines = [
            "---",
            f"id: {app.id}",
            "type: application",
            f"stage: {m.stage}",
            f"opportunity: {app.system.opportunity_id}",
            "---",
            "",
            f"# Application — [[{app.system.opportunity_id}]]",
            "",
            f"**Stage:** {m.stage}",
            f"**Next step:** {m.next_step or 'none'}"
            + (f" (due {m.next_step_due})" if m.next_step_due else ""),
            "",
            "## Materials",
            "",
        ]
        if m.materials:
            lines += [f"- [{mat.status}] {mat.name}" for mat in m.materials]
        else:
            lines.append("_None yet._")
        if m.events:
            lines += ["", "## Events", ""]
            lines += [f"- {e.ts.date()}: {e.event} {('— ' + e.note) if e.note else ''}" for e in m.events]
        lines += ["", "---", "_Generated file — do not edit._", ""]
        return "\n".join(lines)

    def _render_dashboard(
        self,
        opportunities: list[Opportunity],
        orgs: dict[str, Organisation],
        people: list[Person],
        today: date,
    ) -> str:
        open_opps = [
            o
            for o in opportunities
            if o.official.status in ("open", "unknown") and not o.manual.hidden
        ]
        open_opps.sort(
            key=lambda o: (o.official.deadline is None, o.official.deadline or date.max)
        )
        review = [o for o in open_opps if o.derived.needs_review]

        lines = [
            "---",
            "type: dashboard",
            f"generated: {today.isoformat()}",
            "---",
            "",
            "# Research Compass — Dashboard",
            "",
            f"_Generated {today.isoformat()} — run `python -m compass export` to refresh._",
            "",
            "## Action required (deadlines)",
            "",
            "| Opportunity | Organisation | Deadline | Days | Gate | Fit |",
            "|---|---|---|---|---|---|",
        ]
        for o in open_opps:
            org_name = (
                orgs[o.official.org_id].official.name
                if o.official.org_id in orgs
                else o.official.org_id
            )
            fit = o.derived.fit_overall if o.derived.fit_overall is not None else "—"
            days = (
                o.derived.days_to_deadline
                if o.derived.days_to_deadline is not None
                else "—"
            )
            lines.append(
                f"| [[{o.id}\\|{o.official.title}]] | {org_name} | "
                f"{o.official.deadline or 'unknown'} | {days} | "
                f"{o.derived.eligibility_gate} | {fit} |"
            )

        lines += ["", "## Needs manual review", ""]
        if review:
            for o in review:
                reasons = "; ".join(o.derived.eligibility_reasons[:3])
                lines.append(f"- [[{o.id}]] — {reasons}")
        else:
            lines.append("_Nothing waiting._")

        target_orgs = [o for o in orgs.values() if o.manual.target]
        lines += ["", "## Target map", ""]
        if target_orgs:
            for org in target_orgs:
                lines.append(f"- [[{org.id}]] — {org.official.name}")
        else:
            lines.append("_No target organisations marked._")

        lines += ["", "## People", ""]
        if people:
            for p in people:
                lines.append(
                    f"- [[{p.id}]] — {p.official.name} ({p.manual.contact_status})"
                )
        else:
            lines.append("_None tracked yet._")

        lines.append("")
        return "\n".join(lines)
