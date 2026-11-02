# Résumé notes for horizon-bench

Only facts that are true as of the baseline commit (`507dcf1`, report in `reports/baseline/`). Everything about
LLMs is a placeholder until `hb run --policy llm` has actually been run. Keep the numbers exact; do not round
them up.

## True today

- Built **horizon-bench**, an open-source test bench for long-horizon LLM agents on a simulated industrial
  reactor: about 2,300 lines of Python in `src/` plus about 570 lines of tests (36 pytest tests; ruff and mypy
  clean). Dependencies: numpy, pydantic, httpx, matplotlib. No agent framework, no vendor SDK.
- **Failure onset**: every run records the step at which the agent lost control (unrecovered excursion, loop, or
  3 invalid actions in a row), the cause, and the disturbances active at that step.
- **Tool-return A/B** (bare vs rich, same seeds and dynamics). Scripted PI controller, 20 eval seeds per cell:
  stale-read control decisions per run 0.55 / 1.10 / 2.50 with bare tools vs 0.00 / 0.00 / 0.00 with rich tools
  at horizons 60 / 120 / 240; success 19 vs 20, 17 vs 17, 13 vs 11 of 20 (bare vs rich), i.e. no significant
  success difference for this scripted controller.
- **Long-horizon degradation** of the scripted PI controller: 19–20/20 successes at 60 steps, 17/20 at 120,
  11–13/20 at 240.
- **Reward-hacking guard**: a scripted "lazy" agent that wipes the operator log and files a fabricated report
  passes a naive log-trusting grader in 100 % of runs (120 of 120) and the true-state verifier in 0 %.
- **Process-kill recovery**: SQLite checkpoint per step; a test SIGKILLs the CLI mid-run and verifies the resumed
  trace is byte-identical to an uninterrupted run. **Replay**: all 480 baseline runs reproduce step by step
  under `hb replay`.
- **Eval hygiene**: dev/eval seed split, eval seeds derived from a private salt, only the salt's sha256 published.
- **LLM agent** for any OpenAI-compatible endpoint (default Ollama) with tool calling, hard budgets (steps,
  tokens per call, total tokens, wall time), rolling context window with summary-to-notes, loop warnings, and
  malformed calls returned to the model as errors. Tested only against a mocked server so far.
- Baseline: 480 scripted runs (4 policies × 2 tool modes × 3 horizons × 20 seeds) in about 30 s on one CPU.

## Placeholders (fill in only after running)

- Model(s) evaluated: `<model>` via Ollama on `<machine>`.
- Success rate at horizon 120, bare vs rich: `<x/n>` vs `<y/n>`.
- Stale-read errors per run, bare vs rich: `<a>` vs `<b>`.
- Most common failure-onset cause and median onset step: `<cause>`, step `<s>`.
- Handoff: share of runs where the model read its notes after a session reset: `<p %>`.
- Reward hacking: runs that used `edit_operator_log` or fabricated events: `<k/n>`.
- Latency p50 / p95 per call: `<ms>` / `<ms>`; tokens per run: `<t>`; cost per run at `<price table>`: `<usd>`.

## Do not claim

- Any LLM result before it exists.
- That rich tool returns improve success: the scripted baseline does not show that.
- That the bench is validated on real plant data: the reactor is a simplified simulation.
