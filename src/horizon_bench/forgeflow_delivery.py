"""Offline D004 matrix: compare approved ForgeFlow evidence with a simulated inbox."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from horizon_bench.receipt import Inbox, canonical_json, content_digest

WORLDS = ("approved_v2_once", "inbox_empty", "approved_v2_twice", "returned_v1_once", "approval_corrupted")
READERS = ("local_delivered", "upstream_chain", "inbox_count", "full_reconcile")
SOURCE_DIR = "preparation/annual-report-workbench"
INPUTS = ("review-dev.json", "apple-review-v1.json", "apple-review-v2.json")


def canonical_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class Lineage:
    review_sha256: str
    case_id: str
    draft_id: str
    v1: dict[str, Any]
    v2: dict[str, Any]
    payload_digest: str
    provenance: dict[str, Any]


def load_lineage(archive: Path, review_sha256: str) -> Lineage:
    raw = (archive / "review-dev.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != review_sha256:
        raise ValueError("review-dev.json differs from its pinned sha256")
    index = json.loads(raw)
    refs = {ref["file"]: ref for ref in index["artifact_refs"]}
    versions = index["versions"]
    ask_run_ids = {call["run_id"] for call in index["calls"] if call["path"] == "/reports/ask" and call["http"] == 200}
    if index["schema_version"] != 1 or [v["version"] for v in versions] != [1, 2]:
        raise ValueError("expected two v1-schema revisions")
    exports: list[dict[str, Any]] = []
    for entry, expected_state in zip(versions, ("returned", "delivered"), strict=True):
        version = entry["version"]
        name = f"apple-review-v{version}.json"
        raw = (archive / name).read_bytes()
        if len(raw) != refs[name]["bytes"] or hashlib.sha256(raw).hexdigest() != refs[name]["sha256"]:
            raise ValueError(f"file differs from pinned index: {name}")
        export = json.loads(raw)
        payload, events = export["payload"], export["events"]
        if export["schema_version"] != "forgeflow.research.export.v1" or export["state"] != expected_state:
            raise ValueError(f"unexpected export schema or state: {name}")
        digest = canonical_digest(payload)
        if digest != entry["revision_digest"] or digest != export["digest"]:
            raise ValueError(f"revision digest mismatch: {name}")
        if (payload["draft_id"], payload["version"], payload["evidence"]["run_id"]) != (
            index["draft_id"], version, entry["run_id"]
        ):
            raise ValueError(f"revision or tool run belongs to another task: {name}")
        if entry["run_id"] not in index["tool_run_ids"] or entry["run_id"] not in ask_run_ids:
            raise ValueError(f"missing tool run: {name}")
        parent = exports[-1]["digest"] if exports else None
        if payload["parent_digest"] != parent:
            raise ValueError(f"broken revision chain: {name}")
        expected_kinds = ["saved", "submitted", "returned"] if version == 1 else [
            "saved", "submitted", "approved", "delivered"
        ]
        if [event["kind"] for event in events] != expected_kinds:
            raise ValueError(f"unexpected approval or delivery transitions: {name}")
        if any((e["draft"], e["version"], e["digest"]) != (index["draft_id"], version, digest) for e in events):
            raise ValueError(f"event bound to different revision: {name}")
        seqs = [e["seq"] for e in events]
        if seqs != sorted(set(seqs)):
            raise ValueError(f"invalid event order: {name}")
        if version == 2:
            reviewer = events[-2]["actor"]
            if reviewer == payload["owner"] or index["roles"].get(reviewer) != "scripted local reviewer":
                raise ValueError(f"approval does not belong to the declared simulated reviewer: {name}")
        exports.append(export)
    v1, v2 = exports
    if v1["local_receipt"] is not None or v2["local_receipt"] != canonical_digest(v2["events"][-1]):
        raise ValueError("local receipt does not match the delivered event")
    if index["local_receipt"] != v2["local_receipt"]:
        raise ValueError("local receipt does not match the pinned index")
    provenance = {key: index[key] for key in ("tool_run_ids", "versions", "local_receipt")}
    provenance["reported_by_forgeflow"] = {key: index[key] for key in ("model_calls", "driver", "roles")}
    return Lineage(review_sha256, index["case_id"], index["draft_id"], v1, v2,
                   content_digest(v2["payload"], str(v2["payload"]["version"])), provenance)


def _receipts(world: str, lineage: Lineage, inbox: Inbox) -> list[dict[str, Any]]:
    v2, v1 = lineage.v2, lineage.v1
    if world in ("approved_v2_once", "approval_corrupted"):
        inbox.deliver("v2-1", lineage.case_id, v2["payload"], str(v2["payload"]["version"]))
    elif world == "approved_v2_twice":
        for key in ("v2-1", "v2-2"):
            inbox.deliver(key, lineage.case_id, v2["payload"], str(v2["payload"]["version"]))
    elif world == "returned_v1_once":
        inbox.deliver("v1-1", lineage.case_id, v1["payload"], str(v1["payload"]["version"]))
    return inbox.for_task(lineage.case_id)


def _score(reader: str, lineage: Lineage, export: dict[str, Any], receipts: list[dict[str, Any]]) -> bool:
    if reader == "local_delivered":
        return export.get("state") == "delivered"
    if reader == "inbox_count":
        return len(receipts) == 1
    # The independently verified original is the agreed reference of the upstream-only and combined readers.
    chain = export == lineage.v2
    if reader == "upstream_chain":
        return chain
    if reader != "full_reconcile":
        raise ValueError(f"unknown reader: {reader}")
    expected = {
        "task_id": lineage.case_id,
        "payload": lineage.v2["payload"],
        "version": str(lineage.v2["payload"]["version"]),
        "digest": lineage.payload_digest,
    }
    inbox_one = len(receipts) == 1
    receipt_matches = inbox_one and all(receipts[0].get(k) == v for k, v in expected.items())
    return chain and receipt_matches


def run_matrix(lineage: Lineage) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for world in WORLDS:
        export = copy.deepcopy(lineage.v2)
        if world == "approval_corrupted":
            next(e for e in export["events"] if e["kind"] == "approved")["digest"] = "0" * 64
        with tempfile.TemporaryDirectory() as temp:
            inbox = Inbox(Path(temp) / "inbox.sqlite")
            try:
                receipts = _receipts(world, lineage, inbox)
            finally:
                inbox.db.close()
            summary = [{"version": r["version"], "digest": r["digest"], "key": r["idem_key"]} for r in receipts]
        expected = world == "approved_v2_once"
        for reader in READERS:
            accepted = _score(reader, lineage, export, receipts)
            rows.append(
                {
                    "world": world,
                    "reader": reader,
                    "accepted": accepted,
                    "expected": expected,
                    "false_accept": accepted and not expected,
                    "receipt_summary": summary,
                }
            )
    return {
        "upstream": {
            "review_sha256": lineage.review_sha256,
            "case_id": lineage.case_id,
            "draft_id": lineage.draft_id,
            "v1": lineage.v1["digest"],
            "v2": lineage.v2["digest"], "payload_digest": lineage.payload_digest, **lineage.provenance,
        },
        "rows": rows,
    }


def cmd_forgeflow_delivery(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise ValueError("supply the full upstream Git commit")
    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp)
        for name in INPUTS:
            object_name = f"{args.source_commit}:{SOURCE_DIR}/{name}"
            blob = subprocess.run(["git", "-C", str(args.source_repo), "show", object_name], capture_output=True)
            if blob.returncode:
                raise ValueError(f"missing {name} at supplied upstream Git revision")
            (archive / name).write_bytes(blob.stdout)
        result = run_matrix(load_lineage(archive, args.review_sha256))
    result["upstream"].update(repo="https://github.com/langju123456/forgeflow", source_commit=args.source_commit)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return 0
