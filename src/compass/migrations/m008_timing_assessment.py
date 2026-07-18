"""v8: OpportunityDerived gains timing_assessment — a deterministic
timing/readiness axis (actionable_now / prepare_for_current_cycle /
future_target / timing_mismatch / timing_unknown) computed from the vacancy's
start facts and the user's expected MSc completion. Recomputed by rules; the
default is applied here and the real value is written on the next recompute."""

VERSION = 8


def migrate(record: dict) -> dict:
    return record
