"""Dev-only performance instrumentation.

Enabled by setting COMPASS_PERF=1; otherwise every call is a near-zero-cost
no-op. This is a measurement aid so we optimise the layer that is actually slow
(canonical write vs SQLite vs vault export vs serialization) instead of
guessing. It never influences behaviour or output.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager

ENABLED = os.environ.get("COMPASS_PERF") not in (None, "", "0")


class Timings:
    """Accumulates named spans for one logical operation (e.g. one web write)."""

    def __init__(self, title: str = ""):
        self.title = title
        self.spans: dict[str, float] = {}

    @contextmanager
    def measure(self, label: str):
        if not ENABLED:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            ms = (time.perf_counter() - start) * 1000.0
            self.spans[label] = self.spans.get(label, 0.0) + ms

    def report(self) -> None:
        if not ENABLED or not self.spans:
            return
        total = sum(self.spans.values())
        parts = " ".join(f"{k}={v:.1f}ms" for k, v in self.spans.items())
        print(f"[perf] {self.title} total={total:.1f}ms {parts}", flush=True)
