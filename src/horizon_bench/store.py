"""SQLite persistence: one transaction per step writes the step record and a full checkpoint,
so a process killed at any point resumes from the last completed step."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from horizon_bench.spec import RunSpec

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, batch TEXT NOT NULL, spec TEXT NOT NULL,
    status TEXT NOT NULL, verdict TEXT
);
CREATE TABLE IF NOT EXISTS steps (
    run_id TEXT NOT NULL, step INTEGER NOT NULL, record TEXT NOT NULL, PRIMARY KEY (run_id, step)
);
CREATE TABLE IF NOT EXISTS checkpoints (run_id TEXT PRIMARY KEY, step INTEGER NOT NULL, state TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def create_run(self, spec: RunSpec, overwrite: bool = False) -> None:
        with self.db:
            if overwrite:
                for table in ("runs", "steps", "checkpoints"):
                    self.db.execute(f"DELETE FROM {table} WHERE run_id = ?", (spec.run_id,))
            self.db.execute("INSERT INTO runs (run_id, batch, spec, status) VALUES (?, ?, ?, 'running')",
                            (spec.run_id, spec.batch, spec.model_dump_json()))

    def save_step(self, run_id: str, record: dict[str, Any], checkpoint: dict[str, Any]) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO steps VALUES (?, ?, ?)",
                            (run_id, record["step"], json.dumps(record)))
            self.db.execute("INSERT OR REPLACE INTO checkpoints VALUES (?, ?, ?)",
                            (run_id, record["step"], json.dumps(checkpoint)))

    def finish_run(self, run_id: str, verdict: dict[str, Any]) -> None:
        with self.db:
            self.db.execute("UPDATE runs SET status = 'done', verdict = ? WHERE run_id = ?",
                            (json.dumps(verdict), run_id))

    def spec(self, run_id: str) -> RunSpec:
        row = self.db.execute("SELECT spec FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"no run {run_id!r}")
        return RunSpec.model_validate_json(row[0])

    def status(self, run_id: str) -> str | None:
        row = self.db.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return None if row is None else str(row[0])

    def verdict(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT verdict FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def checkpoint(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT state FROM checkpoints WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def records(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT record FROM steps WHERE run_id = ? ORDER BY step", (run_id,))
        return [json.loads(r[0]) for r in rows]

    def runs(self, batches: list[str]) -> list[tuple[RunSpec, dict[str, Any]]]:
        marks = ",".join("?" * len(batches))
        rows = self.db.execute(
            f"SELECT spec, verdict FROM runs WHERE status = 'done' AND batch IN ({marks}) ORDER BY run_id",
            batches)
        return [(RunSpec.model_validate_json(s), json.loads(v)) for s, v in rows]
