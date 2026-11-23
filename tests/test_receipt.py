from __future__ import annotations

import json
from pathlib import Path

import pytest

from horizon_bench.cli import main
from horizon_bench.receipt import (
    EXPECTED_DIGEST,
    PAYLOAD,
    TASK_ID,
    VERSION,
    ClientStore,
    Inbox,
    content_digest,
    initial_worker,
    recover,
    verify,
)


def test_inbox_rejects_same_key_with_different_content(tmp_path: Path) -> None:
    inbox = Inbox(tmp_path / "inbox.sqlite")
    assert inbox.deliver("key", TASK_ID, PAYLOAD, VERSION) == "accepted"
    assert inbox.deliver("key", TASK_ID, PAYLOAD, VERSION) == "duplicate_same_content"
    with pytest.raises(ValueError, match="different content"):
        inbox.deliver("key", TASK_ID, {**PAYLOAD, "q4_thousand_cny": 1}, VERSION)


@pytest.mark.parametrize("fault,expected", [("ack", True), ("request_lost", False), ("receipt_lost_crash", False)])
def test_assume_success_has_the_preregistered_outcomes(tmp_path: Path, fault: str, expected: bool) -> None:
    client, inbox = tmp_path / "client.sqlite", tmp_path / "inbox.sqlite"
    initial_worker(client, inbox, fault, crash=False)  # the process-kill path is covered through the CLI experiment
    recover(client, inbox, "assume_success")
    assert verify(client, inbox, "assume_success", fault, 0, False).success is expected


def test_reconciliation_resends_original_key_then_completes(tmp_path: Path) -> None:
    client, inbox = tmp_path / "client.sqlite", tmp_path / "inbox.sqlite"
    initial_worker(client, inbox, "request_lost", crash=False)
    recover(client, inbox, "reconcile_original_key")
    verdict = verify(client, inbox, "reconcile_original_key", "request_lost", 0, False)
    assert verdict.success and verdict.target_receipts == 1
    assert ClientStore(client).intent(TASK_ID)["digest"] == content_digest()


def test_verifier_rejects_an_extra_wrong_version_for_the_target_task(tmp_path: Path) -> None:
    client, inbox_path = tmp_path / "client.sqlite", tmp_path / "inbox.sqlite"
    initial_worker(client, inbox_path, "ack", crash=False)
    inbox = Inbox(inbox_path)
    inbox.deliver("wrong-version", TASK_ID, PAYLOAD, "catl-fy2025-cfo-v0")
    verdict = verify(client, inbox_path, "assume_success", "ack", 0, False)
    assert content_digest() == EXPECTED_DIGEST
    assert verdict.target_receipts == 2 and not verdict.success


def test_verifier_rejects_an_unexpected_recovery_exit(tmp_path: Path) -> None:
    client, inbox = tmp_path / "client.sqlite", tmp_path / "inbox.sqlite"
    initial_worker(client, inbox, "ack", crash=False)
    verdict = verify(client, inbox, "assume_success", "ack", 0, False, recovery_exit=3)
    assert not verdict.infrastructure_ok and not verdict.success


def test_cli_matrix_uses_real_sigkill_only_after_inbox_write(tmp_path: Path) -> None:
    output = tmp_path / "experiment"
    assert main(["receipt-experiment", "--output", str(output)]) == 0
    before = json.loads((output / "assume_success--request_lost" / "verdict.json").read_text())
    after = json.loads((output / "assume_success--receipt_lost_crash" / "verdict.json").read_text())
    assert before["process_exit"] == 0 and before["inbox"] == []
    assert after["process_exit"] == -9 and after["process_measured"]
    assert len(after["inbox"]) == 1 and after["accepted"]
