from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run
from horizon_bench.report import build_report
from horizon_bench.spec import RunSpec, load_salt, make_run_id, salt_hash, seeds_for
from horizon_bench.store import Store


def test_eval_seeds_are_salted_deterministic_and_disjoint_from_dev() -> None:
    a, b = seeds_for("eval", 50, "salt-1"), seeds_for("eval", 50, "salt-2")
    assert a == seeds_for("eval", 50, "salt-1") and a != b
    assert not set(a) & set(seeds_for("dev", 10_000))
    with pytest.raises(ValueError):
        seeds_for("eval", 3)


def test_salt_file_is_created_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HB_EVAL_SALT", raising=False)
    path = tmp_path / ".hb" / "eval_salt"
    salt = load_salt(path)
    assert load_salt(path) == salt and len(salt) == 32
    monkeypatch.setenv("HB_EVAL_SALT", "from-env")
    assert load_salt(path) == "from-env"


def test_report_manifest_records_salt_hash_not_salt(tmp_path: Path) -> None:
    store = Store(":memory:")
    salt = "very-secret-salt"
    for i, seed in enumerate(seeds_for("eval", 2, salt)):
        for policy in ("pid", "lazy"):
            spec = RunSpec(run_id=make_run_id("r", policy, "rich", 60, "eval", i), batch="r", policy=policy,
                           tools="rich", horizon=60, seed=seed, split="eval", seed_index=i,
                           salt_sha256=salt_hash(salt))
            run(spec, store=store)
    out = build_report(store, ["r"], "r", tmp_path)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["eval_salt_sha256"] == [salt_hash(salt)] and manifest["eval_seed_count"] == 2
    text = "".join(p.read_text() for p in out.glob("*.md")) + json.dumps(manifest)
    assert salt not in text
    for png in ("success_vs_horizon.png", "tools_ab.png", "failure_onset.png"):
        assert (out / png).stat().st_size > 10_000
    report = (out / "report.md").read_text()
    assert "| pid | rich | 60 | 2 |" in report and "n/a (scripted)" in report
