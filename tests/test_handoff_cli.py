"""Public case limits and CLI identities protect the comparison denominator."""

from pathlib import Path

import pytest

from horizon_bench.cli import main
from horizon_bench.report import build_report
from horizon_bench.store import Store


def test_two_memory_modes_in_one_batch_remain_distinct(tmp_path: Path) -> None:
    cli = ["--runs-dir", str(tmp_path / "runs")]
    run = [*cli, "run", "--family", "annual_handoff", "--name", "desk", "--horizon", "12"]
    for mode in ("handoff_last", "handoff_full"):
        assert main([*run, "--variant", mode]) == 0
    store = Store(tmp_path / "runs" / "hb.sqlite")
    runs = store.runs(["desk"])
    assert len(runs) == 4
    assert all(main([*cli, "replay", spec.run_id]) == 0 for spec, _ in runs)
    assert main([*cli, "report", "--name", "desk", "--reports-dir", str(tmp_path)]) == 0
    output = (tmp_path / "desk" / "report.md").read_text()
    assert "handoff_last" in output and "handoff_full" in output
    review = (tmp_path / "desk" / "review.html").read_text()
    assert review.count("<details>") == 4 and "open_source" in review
    with pytest.raises(SystemExit, match="configuration changed"):
        main([*run, "--variant", "handoff_full", "--session-len", "2"])
    reactor = runs[0][0].model_copy(update={"run_id": "older-run", "batch": "older", "family": "reactor"})
    store.create_run(reactor)
    store.finish_run(reactor.run_id, {})
    with pytest.raises(SystemExit, match="single family"):
        build_report(store, ["desk", "older"], "mixed", tmp_path)


@pytest.mark.parametrize("opts", [["--split", "eval"], ["--seeds", "3"],
                                  ["--variant", "handoff_full,handoff_card"]])
def test_public_handoff_rejects_invalid_comparisons(tmp_path: Path, opts: list[str]) -> None:
    with pytest.raises(SystemExit, match="two public dev cases"):
        main(["--runs-dir", str(tmp_path), "run", "--family", "annual_handoff", *opts])
