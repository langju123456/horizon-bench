# Lever retest: plan

Written on 2026-11-13, before any model run with these levers. The code, this plan and the decision rule are in
one commit; results are added to this directory afterwards by `scripts/mac_retest.sh`.

## Why

The first real-model round (2026-11-03, qwen3:8b through Ollama, thinking off) kept control in 4 of 10 runs at
horizon 60 with rich tools and succeeded in 0 of 40 runs overall. In all 30 runs that lost control, a
feed-composition change was active at the onset.

One of those runs was read step by step: `qwen3-8b-nothink-llm-rich-h60-eval007` (onset at step 35). What its
trace shows:

1. It never called `set_coolant` in 60 steps. On the same seed the PI controller moved the valve 18 times and
   stayed in band.
2. It read five sensors in a fixed cycle and then spent a step on a text summary, so it looked at a temperature
   only every 5 to 6 steps.
3. From step 18 (feed change, heat release -13.8 %) its TT-102 readings fell 180.2, 178.5, 178.1, 175.4. Each
   summary called this "within the acceptable range": it compared a reading with the edge of the band (175), not
   with the setpoint (180), and did not react to four readings in a row moving the same way.
4. At step 40 its context was erased, and it had written no note. It then read 174.04 (TT-101) and 172.44
   (TT-102), both below the band, and reported "operating within normal parameters" three more times.

"Too few coolant adjustments" (1.6 to 7.1 per run against 18 to 37 for the PI controller, over the 40 runs) is
therefore the symptom. The retest asks which layer can change the behaviour behind it.

## Three levers, one layer each

| `--variant` | layer | what changes | what stays the same |
|---|---|---|---|
| `ctx_rule` | context | The system prompt gains a three-line control procedure: control to the setpoint; if a reading is more than 1.5 degC off, the next call is `set_coolant` with pct = 50 + 6 x (reading - 180); read the temperature again within 4 steps. | tools, harness |
| `tool_hint` | tool feedback | A fresh temperature reading also returns `setpoint`, `deviation`, `in_band`, `trend_per_step` (same sensor; kept server-side, so it survives the context reset) and, when more than 1.5 degC off, a one-line `hint` naming the direction. | prompt, harness |
| `guard` | control constraint | The harness refuses out-of-order actions. Must act: after a trusted reading more than 1.5 degC off, only `set_coolant` / `set_feed` are accepted (after at most 2 re-reads). Must look: if the last trusted reading is more than 6 steps old, only a temperature read is accepted. A refused call is not executed and the step still passes. Guard state is in the run checkpoint, so it survives the context reset. | prompt, tool results (apart from the refusal message) |

All three use only readings the agent obtained itself; none reads the hidden true state. Code:
`src/horizon_bench/env/reactor_guard.py`. Tests: `tests/test_variants.py`. A run without `--variant` is unchanged:
same records, same replay.

Constants, fixed here: deviation limit 1.5 degC (3 sigma of TT-102 noise), procedure re-read interval 4 steps,
guard reading age 6 steps (the PI controller's own longest gap, at a session boundary), 2 re-reads before control
is forced, trust threshold 0.7 on the `confidence` field (the PI controller's own rule).

## Design

- Model and decoding as on 2026-11-03: qwen3:8b through Ollama with a 16k context, thinking off, temperature 0,
  context budget 8000, sessions of 40 steps.
- Task: horizon 60, rich tools, the first 10 eval seeds of the same salt (sha256 `bd19da65…`), so the same
  ten scenarios. The run script stops if the salt on the machine is a different one.
- Cells, 10 runs each:
  - `retest-base`: no lever. Re-run in the same session, so the model build and the Ollama version are the same
    for every cell.
  - `retest-ctx`, `retest-tool`, `retest-guard`: one lever each.
  - `retest-all`: all three together. Descriptive only.
- Each cell is run once. The prompt text, the hint wording and the constants are not changed after any eval
  result has been seen. No model was run while writing the levers; only scripted policies on public dev seeds
  were used (see below).

## Outcome and decision rule

- Primary outcome: control kept (no failure onset) per run.
- Comparison: each single-lever cell against `retest-base`, paired by seed. *Improved* = seeds where the lever kept
  control and the baseline lost it; *worsened* = the reverse.
- Rule: a lever is called **improved** if improved - worsened >= 5 out of 10 seeds, **worse** if <= -5, otherwise
  **cannot tell at this n**. (5 against 0 is p = 0.031 in a one-sided exact sign test; nothing weaker is called.)
- Secondary, descriptive only: success, time in band, control actions per run, temperature reads per run, steps
  without a tool call, guard refusals per run, notes written, alarms on time, onset step.
- Everything is computed by `scripts/retest_summary.py` from the stored step records; no number is typed by hand.
- If `retest-base` clearly differs from the 2026-11-03 cell (4/10 kept), that is reported as such (the model build
  or Ollama changed), and the comparison still uses `retest-base`.

## Checks made before any model run

Public dev seeds 0 to 19, horizon 60, rich tools, scripted policies only (`python scripts/retest_sanity.py`):

| scripted policy | variants | control kept | success | time in band | guard refusals / run |
|---|---|---|---|---|---|
| pid (reference PI controller) | - | 20/20 | 18/20 | 0.998 | 0.0 |
| pid (reference PI controller) | tool_hint | 20/20 | 18/20 | 0.998 | 0.0 |
| pid (reference PI controller) | guard | 20/20 | 17/20 | 0.998 | 0.1 |
| pid (reference PI controller) | ctx_rule, tool_hint, guard | 20/20 | 17/20 | 0.998 | 0.1 |
| follows the ctx_rule procedure literally | - | 18/20 | 0/20 | 0.963 | 0.0 |
| watcher: never controls | - | 4/20 | 0/20 | 0.666 | 0.0 |
| watcher, obeys refusals with the proportional law | guard | 20/20 | 0/20 | 0.974 | 4.7 |
| watcher, obeys refusals with 5-point moves | guard | 14/20 | 0/20 | 0.908 | 6.2 |

What this says:

- `tool_hint` leaves a controller that already behaves well untouched. The guard refuses it 3 times in 20 runs
  (admin steps at a session boundary while a reading is off target) and costs it one success: the guard is not
  free.
- The `ctx_rule` procedure keeps control in 18 of 20 runs if it is followed to the letter.
- A policy that reproduces the failing pattern (the "watcher") keeps control in 4 of 20 runs; under the guard it
  keeps 20 or 14 of 20, depending on how well it answers a refusal.

So each lever can work in principle. Whether an 8B model follows it is what the retest measures.

Two earlier versions of the guard were rejected by these checks. The first (a reading at least every 4 steps;
control forced after any off-target reading, with no cross-check allowed) cut the PI controller from 20/20 to
15/20 runs in control. The second (6 steps, a cross-check allowed for 2 steps, but still acting on readings the
tool marked as low-confidence) cut it to 18/20. The guard described above is the third.

## Limits

- One 8B local model, 10 seeds per cell, a simulator. A difference smaller than about 5 seeds in 10 cannot be
  shown.
- The levers are first versions and deliberately not tuned on the model. Better wording may exist.
- The guard refuses a call instead of masking the tool list, so every refusal costs a step. Masking at decoding
  time is not available through this endpoint.
- The walkthrough publishes the whole trace of eval seed index 7, including the hidden true state, so that seed is
  no longer blind for future prompt work.
- Success, as opposed to control kept, also needs every alarm acknowledged in time and a correct end-of-shift
  report. None of the levers addresses those.
