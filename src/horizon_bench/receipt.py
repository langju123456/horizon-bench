"""Deterministic receipt experiment for an approved annual-report delivery.

The two SQLite files deliberately model two ownership boundaries: the client may
lose its local acknowledgement after the inbox has durably accepted a report.
The inbox is not a queue implementation or a production delivery guarantee.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

PAYLOAD = {
    "company": "宁德时代",
    "metric": "经营活动产生的现金流量净额",
    "fiscal_year": 2025,
    "annual_thousand_cny": 133219982,
    "q4_thousand_cny": 52559552,
    "source_pages": [11, 12],
}
VERSION = "catl-fy2025-cfo-v1"
TASK_ID = "catl-fy2025-cfo-receipt"
SOURCE_URL = "https://static.cninfo.com.cn/finalpage/2026-03-09/1225002666.PDF"
EXPECTED_PAYLOAD = {
    "company": "宁德时代",
    "metric": "经营活动产生的现金流量净额",
    "fiscal_year": 2025,
    "annual_thousand_cny": 133219982,
    "q4_thousand_cny": 52559552,
    "source_pages": [11, 12],
}
EXPECTED_VERSION = "catl-fy2025-cfo-v1"
EXPECTED_DIGEST = "eedd9faa939cdcf6d469a3ed784890f381d96abf6cb5c1892f966b9d459a5aec"
Fault = Literal["ack", "request_lost", "receipt_lost_crash"]
Strategy = Literal["assume_success", "wait_for_human", "retry_new_key", "reconcile_original_key"]
STRATEGIES: tuple[Strategy, ...] = ("assume_success", "wait_for_human", "retry_new_key", "reconcile_original_key")
FAULTS: tuple[Fault, ...] = ("ack", "request_lost", "receipt_lost_crash")


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_digest(payload: dict[str, object] = PAYLOAD, version: str = VERSION) -> str:
    return hashlib.sha256(canonical_json({"payload": payload, "version": version}).encode()).hexdigest()


class ClientStore:
    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS intents (task_id TEXT PRIMARY KEY, idem_key TEXT NOT NULL, "
            "payload TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL, "
            "status TEXT NOT NULL, events TEXT NOT NULL)"
        )

    def create(self, task_id: str, key: str, payload: dict[str, object], version: str) -> None:
        digest = content_digest(payload, version)
        self.db.execute(
            "INSERT INTO intents VALUES (?, ?, ?, ?, ?, 'prepared', '[]')",
            (task_id, key, canonical_json(payload), version, digest),
        )
        self.db.commit()

    def intent(self, task_id: str) -> dict[str, object]:
        row = self.db.execute(
            "SELECT idem_key, payload, version, digest, status, events FROM intents WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return {
            "task_id": task_id,
            "idem_key": row[0],
            "payload": json.loads(row[1]),
            "version": row[2],
            "digest": row[3],
            "status": row[4],
            "events": json.loads(row[5]),
        }

    def event(self, task_id: str, name: str) -> None:
        intent = self.intent(task_id)
        events = [*cast(list[str], intent["events"]), name]
        self.db.execute("UPDATE intents SET events = ? WHERE task_id = ?", (canonical_json(events), task_id))
        self.db.commit()

    def complete(self, task_id: str, reason: str) -> None:
        self.event(task_id, reason)
        self.db.execute("UPDATE intents SET status = 'completed' WHERE task_id = ?", (task_id,))
        self.db.commit()

    def pending(self, task_id: str, reason: str) -> None:
        self.event(task_id, reason)
        self.db.execute("UPDATE intents SET status = 'pending_human' WHERE task_id = ?", (task_id,))
        self.db.commit()


class Inbox:
    """External-effect store with receiver-owned idempotency and content validation."""

    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS receipts (idem_key TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
            "payload TEXT NOT NULL, "
            "version TEXT NOT NULL, digest TEXT NOT NULL)"
        )

    def deliver(self, key: str, task_id: str, payload: dict[str, object], version: str) -> str:
        digest = content_digest(payload, version)
        row = self.db.execute(
            "SELECT task_id, payload, version, digest FROM receipts WHERE idem_key = ?", (key,)
        ).fetchone()
        incoming = (task_id, canonical_json(payload), version, digest)
        if row is not None:
            if row != incoming:
                raise ValueError("idempotency key reused with different content")
            return "duplicate_same_content"
        self.db.execute("INSERT INTO receipts VALUES (?, ?, ?, ?, ?)", (key, *incoming))
        self.db.commit()
        return "accepted"

    def find(self, key: str) -> dict[str, object] | None:
        row = self.db.execute(
            "SELECT task_id, payload, version, digest FROM receipts WHERE idem_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return {"idem_key": key, "task_id": row[0], "payload": json.loads(row[1]), "version": row[2], "digest": row[3]}

    def for_task(self, task_id: str) -> list[dict[str, object]]:
        rows = self.db.execute(
            "SELECT idem_key, task_id, payload, version, digest FROM receipts WHERE task_id = ? ORDER BY idem_key",
            (task_id,),
        )
        return [
            {"idem_key": r[0], "task_id": r[1], "payload": json.loads(r[2]), "version": r[3], "digest": r[4]}
            for r in rows
        ]

    def all(self) -> list[dict[str, object]]:
        rows = self.db.execute("SELECT idem_key, task_id, payload, version, digest FROM receipts ORDER BY idem_key")
        return [
            {"idem_key": r[0], "task_id": r[1], "payload": json.loads(r[2]), "version": r[3], "digest": r[4]}
            for r in rows
        ]


@dataclass(frozen=True)
class Verdict:
    strategy: str
    fault: str
    process_exit: int
    recovery_exit: int
    process_measured: bool
    infrastructure_ok: bool
    accepted: bool
    target_receipts: int
    local_status: str
    success: bool
    reason: str
    inbox: list[dict[str, object]]
    events: list[str]


def _first_attempt(client: ClientStore, inbox: Inbox, fault: Fault, crash: bool) -> None:
    intent = client.intent(TASK_ID)
    client.event(TASK_ID, "send_original")
    if fault == "request_lost":
        client.event(TASK_ID, "simulated_timeout_before_inbox")
        return
    inbox.deliver(str(intent["idem_key"]), TASK_ID, cast(dict[str, object], intent["payload"]), str(intent["version"]))
    if fault == "receipt_lost_crash":
        if crash:
            # This is intentionally after the independent SQLite commit and before any local completion.
            os.kill(os.getpid(), signal.SIGKILL)
        client.event(TASK_ID, "simulated_crash_after_inbox_write")
        return
    client.complete(TASK_ID, "ack_received")


def initial_worker(client_path: Path, inbox_path: Path, fault: Fault, crash: bool) -> None:
    client = ClientStore(client_path)
    inbox = Inbox(inbox_path)
    if client.db.execute("SELECT count(*) FROM intents").fetchone()[0] == 0:
        client.create(TASK_ID, "delivery-001", PAYLOAD, VERSION)
    _first_attempt(client, inbox, fault, crash)


def recover(client_path: Path, inbox_path: Path, strategy: Strategy) -> None:
    client = ClientStore(client_path)
    inbox = Inbox(inbox_path)
    intent = client.intent(TASK_ID)
    if intent["status"] == "completed":
        return
    # Both timeout faults reach this same durable observation. The strategy receives neither fault nor inbox internals.
    client.event(TASK_ID, "timeout_observed_after_restart")
    if strategy == "assume_success":
        client.complete(TASK_ID, "timeout_assumed_success")
    elif strategy == "wait_for_human":
        client.pending(TASK_ID, "timeout_waiting_for_human")
    elif strategy == "retry_new_key":
        new_key = f"{intent['idem_key']}-retry-2"
        inbox.deliver(new_key, TASK_ID, cast(dict[str, object], intent["payload"]), str(intent["version"]))
        client.complete(TASK_ID, "timeout_retried_with_new_key")
    else:
        received = inbox.find(str(intent["idem_key"]))
        if received is None:
            inbox.deliver(
                str(intent["idem_key"]), TASK_ID, cast(dict[str, object], intent["payload"]), str(intent["version"])
            )
            client.event(TASK_ID, "reconcile_absent_then_resend_original")
        elif received["digest"] != intent["digest"] or received["version"] != intent["version"]:
            client.pending(TASK_ID, "reconcile_found_mismatch")
            return
        else:
            client.event(TASK_ID, "reconcile_found_valid_original")
        client.complete(TASK_ID, "reconcile_confirmed")


def verify(
    client_path: Path,
    inbox_path: Path,
    strategy: Strategy,
    fault: Fault,
    exit_code: int,
    measured: bool,
    recovery_exit: int = 0,
) -> Verdict:
    client = ClientStore(client_path)
    inbox = Inbox(inbox_path)
    intent = client.intent(TASK_ID)
    target_receipts = inbox.for_task(TASK_ID)
    valid = len(target_receipts)
    receipt = target_receipts[0] if valid == 1 else None
    accepted = (
        receipt is not None
        and receipt
        == {
            "idem_key": receipt["idem_key"],
            "task_id": TASK_ID,
            "payload": EXPECTED_PAYLOAD,
            "version": EXPECTED_VERSION,
            "digest": EXPECTED_DIGEST,
        }
        and content_digest(cast(dict[str, object], receipt["payload"]), cast(str, receipt["version"]))
        == EXPECTED_DIGEST
    )
    expected_initial_exit = -signal.SIGKILL if fault == "receipt_lost_crash" else 0
    infrastructure_ok = exit_code == expected_initial_exit and recovery_exit == 0
    process_ok = fault != "receipt_lost_crash" or measured
    success = accepted and intent["status"] == "completed" and process_ok and infrastructure_ok
    reason = "one_valid_receipt_and_local_completed" if success else "receipt_local_or_infrastructure_failed"
    return Verdict(
        strategy,
        fault,
        exit_code,
        recovery_exit,
        measured,
        infrastructure_ok,
        accepted,
        valid,
        str(intent["status"]),
        success,
        reason,
        inbox.all(),
        cast(list[str], intent["events"]),
    )


def write_verdict(path: Path, verdict: Verdict) -> None:
    path.write_text(json.dumps(asdict(verdict), ensure_ascii=False, indent=2) + "\n")
