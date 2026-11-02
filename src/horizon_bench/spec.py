"""Run specification and the dev/eval seed split.

Dev seeds are public (0, 1, 2, ...). Eval seeds are derived from a private salt, are disjoint
from dev seeds by construction (bit 31 set), and only sha256(salt) is ever written to disk next
to results, so a manifest proves which salt was used without revealing it.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

Split = Literal["dev", "eval"]
SALT_ENV = "HB_EVAL_SALT"
DEFAULT_SALT_FILE = Path(".hb/eval_salt")


class RunSpec(BaseModel):
    run_id: str
    batch: str
    family: str = "reactor"
    policy: str
    tools: Literal["bare", "rich"]
    horizon: int
    session_len: int = 40
    seed: int
    split: Split
    seed_index: int
    stale_after: int = 3  # a decision based on information older than this many steps is stale
    llm: dict[str, Any] | None = None  # LLMConfig without the api key
    prices: dict[str, list[float]] = {}  # model -> [USD per 1M input tokens, USD per 1M output tokens]


def make_run_id(batch: str, policy: str, tools: str, horizon: int, split: str, index: int) -> str:
    return f"{batch}-{policy}-{tools}-h{horizon}-{split}{index:03d}"


def load_salt(path: Path = DEFAULT_SALT_FILE, create: bool = True) -> str:
    """Salt from $HB_EVAL_SALT, else from `path` (created with a random salt if missing)."""
    if os.environ.get(SALT_ENV):
        return os.environ[SALT_ENV]
    if path.exists():
        return path.read_text().strip()
    if not create:
        raise FileNotFoundError(f"no eval salt: set ${SALT_ENV} or create {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_hex(16)
    path.write_text(salt + "\n")
    return salt


def salt_hash(salt: str) -> str:
    return hashlib.sha256(salt.encode()).hexdigest()


def seeds_for(split: Split, n: int, salt: str | None = None) -> list[int]:
    if split == "dev":
        return list(range(n))
    if salt is None:
        raise ValueError("eval seeds need a salt")
    out = []
    for i in range(n):
        h = int.from_bytes(hashlib.sha256(f"{salt}:{i}".encode()).digest()[:4], "big")
        out.append(h | (1 << 31))  # dev seeds are small integers, so the splits never overlap
    return out
