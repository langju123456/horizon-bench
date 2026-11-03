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

## Real-model results (2026-11-03, report in `reports/llm-vs-baseline/`)

- Model evaluated: `qwen3:8b` via Ollama 0.32.1 on a MacBook Air (24 GB), thinking off, 16k context; 40 runs
  (10 eval seeds × bare/rich × horizons 60/120), against the scripted baseline re-run on the same eval seeds.
- Success: 0/40. Success at horizon 120, bare vs rich: 0/10 vs 0/10 (PI controller: 17/20 vs 16/20).
  Control kept at 120 steps: 2/10 bare, 0/10 rich.
- Failure onset: lost control in 30/40 runs; a feed-composition change (heat-release step) was active at the onset in
  all 30. Median onset step 41–46 depending on the cell; 20 of 30 excursions went below the band.
- Behaviour behind it: 1.6–7.1 coolant adjustments per run vs 18–37 for the PI controller; 9–21 steps per run lost to
  replies without a tool call.
- Stale-basis decisions per run, bare vs rich: 0.50 vs 1.80 at 60 steps, 3.20 vs 6.00 at 120 steps.
- Handoff: the model read its notes after 60 of 60 context resets, but in three of four cells it had written almost
  none, so 4 of 40 reads returned anything.
- Reward hacking: log-edit loophole used in 0/40 runs; it called `finish` in 4/40 runs and 3 of those 4 reports listed
  events that never happened (flagged as fabricated). Alarms: 195 of 249 acknowledged late.
- Latency p50 / p95 per call: 2.3–2.8 s / 9.2–11.9 s; tokens per run: 123k–356k; cost per run: 0 (local model).
- Engineering found by running it for real: a desktop proxy answered localhost with 502 (the client now ignores proxy
  settings for loopback endpoints), and Qwen3 kept thinking despite `/no_think` (about 72 s per call) until the agent
  sent `reasoning_effort: "none"`; the run script now stops if completions stay long.

One résumé line that is true: *Ran qwen3:8b on horizon-bench (40 runs): 0 successes; it lost control in 30 runs, all
under a feed-composition change, after adjusting the coolant 5–11× less often than a PI baseline; it read its handoff
notes after every reset but had rarely written any, and 3 of its 4 final reports fabricated events.*

## Do not claim

- That rich tool returns improve success: neither the scripted baseline nor the qwen3:8b runs show that (10 runs per
  LLM cell; the differences are inside the noise).
- That the context reset causes the failures: onsets cluster around the first reset (step 40) but also start before
  it; this run does not isolate the reset.
- Anything about other models, larger models, or qwen3 with thinking on: not run.
- That the bench is validated on real plant data: the reactor is a simplified simulation.
