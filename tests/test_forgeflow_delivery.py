import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from horizon_bench.cli import main
from horizon_bench.forgeflow_delivery import SOURCE_DIR, canonical_digest, load_lineage, run_matrix


def archive(path: Path, *, stale_event: bool = False, fake_digest: bool = False) -> str:
    index: dict[str, Any] = {"schema_version": 1, "case_id": "case", "draft_id": "draft", "tool_run_ids": [],
                             "versions": [], "artifact_refs": [], "driver": "test fixture", "model_calls": 0,
                             "roles": {"reviewer": "scripted local reviewer"}, "calls": []}
    parent = None
    kinds_by_version = (["saved", "submitted", "returned"], ["saved", "submitted", "approved", "delivered"])
    for version, kinds in enumerate(kinds_by_version, start=1):
        run_id = f"run-{version}"
        payload = {"draft_id": "draft", "owner": "author", "version": version, "parent_digest": parent,
                   "evidence": {"run_id": run_id}}
        digest = "f" * 64 if fake_digest and version == 2 else canonical_digest(payload)
        events = [{"draft": "draft", "version": version, "kind": k, "digest": digest, "seq": i + 1,
                   "actor": "reviewer" if k in ("approved", "returned") else "author"} for i, k in enumerate(kinds)]
        if version == 2 and stale_event:
            events[-2]["digest"] = parent
        receipt = canonical_digest(events[-1]) if version == 2 else None
        export = {"schema_version": "forgeflow.research.export.v1", "state": kinds[-1], "digest": digest,
                  "payload": payload, "events": events, "local_receipt": receipt}
        name = f"apple-review-v{version}.json"
        raw = json.dumps(export).encode()
        (path / name).write_bytes(raw)
        index["artifact_refs"].append({"file": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        index["versions"].append({"version": version, "revision_digest": digest, "run_id": run_id})
        index["tool_run_ids"].append(run_id)
        index["calls"].append({"path": "/reports/ask", "http": 200, "run_id": run_id})
        index["local_receipt"] = receipt
        parent = digest
    raw = json.dumps(index).encode()
    (path / "review-dev.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_same_local_receipt_can_hide_three_different_inbox_failures(tmp_path: Path) -> None:
    inputs = tmp_path / SOURCE_DIR
    inputs.mkdir(parents=True)
    pin = archive(inputs)
    report = run_matrix(load_lineage(inputs, pin))
    rows = report["rows"]
    assert len(rows) == 20
    assert [sum(r["false_accept"] for r in rows if r["reader"] == reader)
            for reader in ("local_delivered", "upstream_chain", "inbox_count", "full_reconcile")] == [4, 3, 2, 0]
    assert all(r["accepted"] for r in rows if r["world"] == "approved_v2_once")
    out = tmp_path / "result.json"
    git = ["git", "-C", str(tmp_path)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "--", SOURCE_DIR], check=True)
    subprocess.run([*git, "-c", "commit.gpgsign=false", "-c", "user.name=fixture", "-c", "user.email=test@example.test",
                    "commit", "-qm", "fixture"], check=True)
    commit = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    args = ["forgeflow-delivery", "--source-repo", str(tmp_path), "--review-sha256", pin, "--output", str(out),
            "--source-commit", commit]
    assert main(args) == 0
    assert json.loads(out.read_text())["upstream"]["tool_run_ids"] == ["run-1", "run-2"]
    with pytest.raises(FileExistsError):
        main(args)
    with pytest.raises(ValueError, match="supplied upstream Git revision"):
        main([*args[:-1], "b" * 40])


def test_unchanged_index_rejects_an_edited_export(tmp_path: Path) -> None:
    pin = archive(tmp_path)
    with pytest.raises(ValueError, match="pinned sha256"):
        load_lineage(tmp_path, "f" * 64)
    with (tmp_path / "apple-review-v2.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="differs from pinned index"):
        load_lineage(tmp_path, pin)


@pytest.mark.parametrize("broken,expected", [("stale_event", "bound to different"), ("fake_digest", "digest mismatch")])
def test_a_pinned_file_still_needs_a_valid_approval_chain(tmp_path: Path, broken: str, expected: str) -> None:
    pin = archive(tmp_path, **{broken: True})
    with pytest.raises(ValueError, match=expected):
        load_lineage(tmp_path, pin)
