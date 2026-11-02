"""Per-step JSONL traces, cost estimates and usage summaries.

Prices are USD per 1M tokens and come only from the user's price table: a local Ollama model
costs nothing, and nothing here guesses a vendor's price list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

FLAGS = ("loop", "stale_read_used", "invalid_args", "loophole_used")


def cost_usd(model: str | None, prompt_tokens: int, completion_tokens: int,
             prices: dict[str, list[float]]) -> float:
    if not model or (prompt_tokens == 0 and completion_tokens == 0):
        return 0.0
    price_in, price_out = prices.get(model, prices.get("*", [0.0, 0.0]))
    return (prompt_tokens * price_in + completion_tokens * price_out) / 1e6


def load_prices(path: str | Path | None) -> dict[str, list[float]]:
    if path is None:
        return {}
    data = json.loads(Path(path).read_text())
    return {k: [float(v[0]), float(v[1])] for k, v in data.items()}


class TraceWriter:
    """Appends one JSON object per step and flushes, so a live run can be tailed."""

    def __init__(self, path: Path, records: list[dict[str, Any]] | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with path.open("w") as f:  # rewrite from the store on start/resume: SQLite is the source of truth
            for r in records or []:
                f.write(json.dumps(r) + "\n")

    def write(self, record: dict[str, Any]) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")


def summarize_usage(records: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [r for r in records if r.get("llm_call")]
    lat = [float(r["llm_latency_ms"]) for r in calls]
    return {
        "llm_calls": len(calls),
        "prompt_tokens": sum(int(r["prompt_tokens"]) for r in records),
        "completion_tokens": sum(int(r["completion_tokens"]) for r in records),
        "cost_usd": round(sum(float(r["cost_usd"]) for r in records), 6),
        "latency_ms": lat,
        "max_context_tokens": max((int(r["context_tokens"]) for r in calls), default=0),
    }


def percentile(values: list[float], q: float) -> float | None:
    return float(np.percentile(values, q)) if values else None
