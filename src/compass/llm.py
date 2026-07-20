"""Live LLM analysis client (OpenAI-compatible).

Whitelist by construction: the ONLY payload sent to the API is the packet built
by analysis_io.prepare_packet (official posting text + the whitelisted profile
summary + taxonomy + target identity + non-private constraints). A defensive
assertion additionally refuses any packet that carries private keys, so
vault/notes, the full CV, letters and correspondence can never leak even if a
future change to prepare_packet slipped.

Safety rails from config/models.yaml: a hard per-run item cap and, when a token
price is configured, a daily cost cap. JSON response with one retry; anything
still unparseable leaves the item unanalysed (import validation quarantines bad
output — the AI layer is never written from invalid data).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from .config import Config

# Defensive: none of these may appear anywhere in an outbound packet.
_FORBIDDEN_PACKET_KEYS = {
    "cv", "full_cv", "resume", "vault_notes", "notes", "recommendation_letter",
    "recommendation_letters", "correspondence", "manuscript", "private_notes",
}


class LLMError(Exception):
    pass


class NotConfigured(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


def _deep_keys(obj) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k).lower())
            keys |= _deep_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            keys |= _deep_keys(v)
    return keys


def assert_whitelisted(packet: dict) -> None:
    if packet.get("packet_type") != "compass-analysis-packet":
        raise LLMError("refusing to send: not a compass-analysis-packet")
    bad = _FORBIDDEN_PACKET_KEYS & _deep_keys(packet)
    if bad:
        raise LLMError(f"refusing to send packet carrying private keys: {sorted(bad)}")


class UsageLog:
    """Per-day token + estimated-cost accumulator (data/status/llm_usage.json)."""

    def __init__(self, cfg: Config):
        self.path: Path = cfg.paths.status / "llm_usage.json"

    def _load(self) -> dict:
        if self.path.is_file():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return {}
        return {}

    def spent_today(self, today: date) -> float:
        return float(self._load().get(today.isoformat(), {}).get("cost_usd", 0.0))

    def add(self, today: date, tokens: int, cost: float) -> None:
        data = self._load()
        day = data.setdefault(today.isoformat(), {"tokens": 0, "cost_usd": 0.0, "calls": 0})
        day["tokens"] += int(tokens)
        day["cost_usd"] = round(day["cost_usd"] + float(cost), 6)
        day["calls"] += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# A completion function takes (system, user) and returns
# (content, input_tokens, output_tokens).
CompletionFn = Callable[[str, str], "tuple[str, int, int]"]


class LLMClient:
    def __init__(self, cfg: Config, completion_fn: Optional[CompletionFn] = None):
        self.cfg = cfg
        api = cfg.models.get("api") or {}
        limits = cfg.models.get("limits") or {}
        self.model: Optional[str] = api.get("model")
        self.temperature = api.get("temperature", 0.2)
        # Per-1M-token USD prices (01tree bills input and output separately). A
        # single price_per_1k_tokens is still honoured as a fallback for both.
        legacy = api.get("price_per_1k_tokens")
        legacy_1m = legacy * 1000 if legacy else None
        self.price_in_1m = api.get("price_per_1m_input", legacy_1m)
        self.price_out_1m = api.get("price_per_1m_output", legacy_1m)
        self.daily_cost_limit = limits.get("daily_cost_limit_usd")
        self.max_items = int(limits.get("max_ai_items_per_run", 20))
        self._complete = completion_fn or self._openai_complete
        self.usage = UsageLog(cfg)

    def configured(self) -> bool:
        return bool(self.cfg.api_key and self.cfg.api_base_url and self.model)

    # -- real API call (only reached when a real completion_fn wasn't injected) --
    def _openai_complete(self, system: str, user: str) -> tuple[str, int]:
        from openai import OpenAI  # imported lazily so tests need no network/SDK use

        client = OpenAI(api_key=self.cfg.api_key, base_url=self.cfg.api_base_url)
        resp = client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        u = getattr(resp, "usage", None)
        pin = int(getattr(u, "prompt_tokens", 0) or 0) if u else 0
        pout = int(getattr(u, "completion_tokens", 0) or 0) if u else 0
        return resp.choices[0].message.content or "", pin, pout

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        c = 0.0
        if self.price_in_1m:
            c += (input_tokens / 1_000_000.0) * float(self.price_in_1m)
        if self.price_out_1m:
            c += (output_tokens / 1_000_000.0) * float(self.price_out_1m)
        return c

    def _priced(self) -> bool:
        return bool(self.price_in_1m or self.price_out_1m)

    def _budget_ok(self, today: date) -> bool:
        if self.daily_cost_limit is None or not self._priced():
            return True                       # no $ cap configured -> item cap only
        return self.usage.spent_today(today) < float(self.daily_cost_limit)

    def analyze_packet(self, packet: dict, prompt_text: str, today: date) -> dict:
        """Send one whitelisted packet, return the parsed {'results': [...]}."""
        assert_whitelisted(packet)
        if not self.configured():
            raise NotConfigured(
                "LLM not configured: set model in config/models.yaml and "
                "COMPASS_API_KEY / COMPASS_API_BASE_URL in .env")
        if not self._budget_ok(today):
            raise BudgetExceeded(
                f"daily cost limit ${self.daily_cost_limit} reached")

        system = prompt_text.strip() + "\n\nRESULT CONTRACT:\n" + \
            json.dumps(packet.get("result_contract", {}), ensure_ascii=False)
        user = json.dumps({k: v for k, v in packet.items()
                           if k != "result_contract"}, ensure_ascii=False)

        raw, tin, tout = self._complete(system, user)
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            raw, tin2, tout2 = self._complete(
                system + "\n\nReturn ONLY a valid JSON object, nothing else.", user)
            tin += tin2
            tout += tout2
            parsed = json.loads(raw)          # still bad -> raises; caller reports
        self.usage.add(today, tin + tout, self._cost(tin, tout))
        return parsed
