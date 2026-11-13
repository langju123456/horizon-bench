#!/bin/bash
# Lever retest on the Mac that produced the 2026-11-03 results. One command, unattended:
#
#   curl -fsSL https://raw.githubusercontent.com/langju123456/horizon-bench/retest-levers/scripts/mac_retest.sh | bash
#
# It re-runs the failing cell (qwen3:8b, rich tools, horizon 60, the same 10 eval seeds) once without any
# lever and once per lever, each cell 10 runs:
#   retest-base   no lever (baseline, re-run so that model build and Ollama version are the same for all cells)
#   retest-guard  --variant guard       control constraint: the harness refuses out-of-order actions
#   retest-tool   --variant tool_hint   tool feedback: deviation / trend / hint in temperature readings
#   retest-ctx    --variant ctx_rule    context: a control procedure in the system prompt
#   retest-all    all three (descriptive only)
# After every cell it writes reports/retest/ (summary.md, walkthrough-eval007.md, report.md, STATUS.md),
# commits and pushes to the retest-levers branch. The plan and the decision rule were committed before
# any of these runs: reports/retest/PLAN.md.
#
# About 3-4 hours on a MacBook Air (3000 model calls). The Terminal window can be closed once it says
# "started". Keep the lid open and the charger in. Running the one-liner again continues where it stopped:
# finished runs are skipped and an interrupted run resumes from its checkpoint.
# Overrides: HB_MODEL, HB_SEEDS (default 10), HB_CELLS="base guard" to run a subset.
# Written for the stock macOS bash 3.2.

set -uo pipefail
export NO_PROXY="localhost,127.0.0.1,::1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"
OLLAMA_URL="http://127.0.0.1:11434"

REPO_URL="https://github.com/langju123456/horizon-bench.git"
BRANCH="retest-levers"
DIR="${HB_DIR:-$HOME/code/horizon-bench}"
LOG_DIR="$HOME/.horizon-bench"
LOG="$LOG_DIR/retest.log"
OUT="reports/retest"
WALK_INDEX=7
# sha256 of the eval salt that produced the 2026-11-03 results (reports/mac-run/STATUS.md). The retest is only
# comparable on the same seeds, so a different salt stops the run.
EXPECTED_SALT="bd19da6595bd653ec071cda68a4be0b7e529b4a1e4ad3d252671394c4179590e"

launch() {
  mkdir -p "$LOG_DIR" "$(dirname "$DIR")"
  if pgrep -f "mac_llm_run.sh --pipeline" >/dev/null 2>&1; then
    echo "the original mac_llm_run.sh pipeline is still running; wait for it or stop it first"; exit 1
  fi
  if pgrep -f "mac_retest.sh --pipeline" >/dev/null 2>&1; then
    echo "stopping the previous retest to restart it on the latest code (finished runs are kept)"
    pkill -f "mac_retest.sh --pipeline"; pkill -f "\.venv/bin/hb run"; sleep 2
  fi
  if [ -d "$DIR/.git" ]; then
    git -C "$DIR" fetch -q origin "$BRANCH" || { echo "git fetch failed in $DIR"; exit 1; }
    git -C "$DIR" checkout -q "$BRANCH" 2>/dev/null || git -C "$DIR" checkout -q -b "$BRANCH" "origin/$BRANCH" \
      || { echo "could not switch $DIR to $BRANCH (uncommitted changes?)"; exit 1; }
    git -C "$DIR" pull --rebase -q origin "$BRANCH" || { echo "git pull failed in $DIR"; exit 1; }
  else
    git clone -q -b "$BRANCH" "$REPO_URL" "$DIR" || { echo "git clone failed"; exit 1; }
  fi
  nohup caffeinate -ims /bin/bash "$DIR/scripts/mac_retest.sh" --pipeline >>"$LOG" 2>&1 &
  echo $! >"$LOG_DIR/retest.pid"
  echo "started in the background (pid $!). You can close this window."
  echo "log:      $LOG"
  echo "progress: https://github.com/langju123456/horizon-bench/blob/$BRANCH/$OUT/STATUS.md"
}

# ---------------------------------------------------------------------------------------------
log() { echo "[$(date '+%m-%d %H:%M:%S')] $*"; }

CELLS_DONE=""
status_file() {
  local state="$1" detail="$2"
  mkdir -p "$DIR/$OUT"
  {
    echo "# Lever retest: run status"
    echo
    echo "- state: **$state**"
    echo "- updated: $(date '+%Y-%m-%d %H:%M %Z')"
    echo "- code: $(git -C "$DIR" rev-parse --short HEAD 2>/dev/null) on $BRANCH"
    echo "- machine: $(sysctl -n hw.model 2>/dev/null), $(($(sysctl -n hw.memsize) / 1073741824)) GB, macOS $(sw_vers -productVersion 2>/dev/null)"
    echo "- ollama: $("${OLLAMA:-ollama}" --version 2>/dev/null | tail -1)"
    echo "- model: ${MODEL:-?} (as ${HBM:-?}, num_ctx 16384), digest ${DIGEST:-?}, thinking: off"
    echo "- eval salt sha256: ${SALT_HASH:-?}"
    echo "- cells done: ${CELLS_DONE:-none}"
    echo
    echo "$detail"
    echo
    echo '## Last 40 log lines'
    echo
    echo '```'
    tail -n 40 "$LOG" 2>/dev/null
    echo '```'
  } >"$DIR/$OUT/STATUS.md"
}

publish() {
  local msg="$1"
  cd "$DIR" || return 1
  git add "$OUT" >/dev/null 2>&1
  if git diff --cached --quiet; then return 0; fi
  git -c user.name="Lang Ju" -c user.email="langju123456@gmail.com" commit -q -m "$msg"
  git pull --rebase -q origin "$BRANCH" || log "WARN: git pull --rebase failed"
  if git push -q origin "HEAD:$BRANCH"; then log "pushed: $msg"; else log "WARN: push failed (results stay in $DIR/$OUT)"; fi
}

fail() {
  log "FAILED: $1"
  status_file "failed" "Stopped at: $1"
  publish "Retest: failed at $1"
  osascript -e "display notification \"stopped: $1\" with title \"horizon-bench retest\"" >/dev/null 2>&1
  rm -f "$LOG_DIR/retest.pid"
  exit 1
}

find_python() {
  local c
  for c in python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 "$HOME/.homebrew/bin/python3" \
           /usr/local/bin/python3 "$HOME/miniconda3/bin/python3" "$HOME/anaconda3/bin/python3" python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      command -v "$c"; return 0
    fi
  done
  return 1
}

find_ollama() {
  local c
  for c in ollama /Applications/Ollama.app/Contents/Resources/ollama /opt/homebrew/bin/ollama \
           "$HOME/.homebrew/bin/ollama" /usr/local/bin/ollama; do
    if command -v "$c" >/dev/null 2>&1; then command -v "$c"; return 0; fi
  done
  return 1
}

variant_of() {
  case "$1" in
    base) echo "" ;;
    guard) echo "guard" ;;
    tool) echo "tool_hint" ;;
    ctx) echo "ctx_rule" ;;
    all) echo "ctx_rule,tool_hint,guard" ;;
    *) return 1 ;;
  esac
}

summarize() {
  .venv/bin/python scripts/retest_summary.py --out "$OUT" --walk-index "$WALK_INDEX" || return 1
  .venv/bin/hb report --name retest --batch retest-base --batch retest-guard --batch retest-tool \
        --batch retest-ctx --batch retest-all >/dev/null || return 1
}

pipeline() {
  OLLAMA=""; MODEL=""; HBM=""; SALT_HASH=""; DIGEST=""
  cd "$DIR" || fail "repo directory missing"
  log "==== horizon-bench lever retest starts ($(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD)) ===="
  [ -f "$OUT/PLAN.md" ] || fail "reports/retest/PLAN.md is missing: the plan must be committed before any run"

  PY="$(find_python || true)"
  [ -n "$PY" ] || fail "no Python >= 3.11"
  OLLAMA="$(find_ollama || true)"
  [ -n "$OLLAMA" ] || fail "ollama not found"
  if ! curl -sf --noproxy '*' $OLLAMA_URL/api/tags >/dev/null; then
    log "starting ollama serve"
    nohup "$OLLAMA" serve >>"$LOG_DIR/ollama.log" 2>&1 &
    for _ in $(seq 1 60); do curl -sf --noproxy '*' $OLLAMA_URL/api/tags >/dev/null && break; sleep 1; done
  fi
  curl -sf --noproxy '*' $OLLAMA_URL/api/tags >/dev/null || fail "ollama server did not come up"

  local mem_gb
  mem_gb=$(($(sysctl -n hw.memsize) / 1073741824))
  if [ -n "${HB_MODEL:-}" ]; then MODEL="$HB_MODEL"; elif [ "$mem_gb" -ge 15 ]; then MODEL="qwen3:8b"; else MODEL="qwen3:4b"; fi
  HBM="hb-$(echo "$MODEL" | tr ':./' '---')"
  "$OLLAMA" pull "$MODEL" || fail "ollama pull $MODEL"
  printf 'FROM %s\nPARAMETER num_ctx 16384\n' "$MODEL" >"$LOG_DIR/Modelfile"
  "$OLLAMA" create "$HBM" -f "$LOG_DIR/Modelfile" >/dev/null || fail "ollama create $HBM"
  DIGEST="$("$OLLAMA" list 2>/dev/null | awk -v m="$MODEL" '$1 == m {print $2}' | head -1)"
  log "model $MODEL as $HBM, digest ${DIGEST:-unknown}, $("$OLLAMA" --version 2>/dev/null | tail -1)"

  if [ ! -x .venv/bin/hb ]; then "$PY" -m venv .venv || fail "python venv"; fi
  .venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1
  .venv/bin/python -m pip install -q -e . || fail "pip install"
  HB=".venv/bin/hb"
  "$HB" run --help | grep -q -- "--variant" || fail "this checkout has no --variant option (wrong branch?)"
  SALT_HASH="$(.venv/bin/python -c 'from horizon_bench.spec import load_salt, salt_hash; print(salt_hash(load_salt(create=False)))' 2>/dev/null)"
  [ -n "$SALT_HASH" ] || fail "no eval salt in $DIR/.hb (this must be the Mac that ran the 2026-11-03 experiment)"
  if [ "$SALT_HASH" != "$EXPECTED_SALT" ] && [ "${HB_ALLOW_OTHER_SALT:-0}" != "1" ]; then
    fail "eval salt differs from the 2026-11-03 run (got ${SALT_HASH:0:12}): the seeds would not be the same"
  fi
  log "eval salt sha256 $SALT_HASH (same seeds as the 2026-11-03 run)"
  status_file "running" "Phase: smoke test"

  local pre
  pre="$(curl -sS --noproxy '*' -m 600 "$OLLAMA_URL/v1/chat/completions" -H 'Content-Type: application/json' \
        -d "{\"model\": \"$HBM\", \"messages\": [{\"role\": \"user\", \"content\": \"Reply with OK.\"}], \"max_tokens\": 20, \"reasoning_effort\": \"none\"}" 2>&1)"
  case "$pre" in *'"choices"'*) ;; *) fail "Ollama preflight call failed: $(echo "$pre" | head -c 200)" ;; esac

  # Smoke: one PUBLIC dev seed, 20 steps, all three levers on, to catch a crash before the long cells.
  local smoke_out
  smoke_out="$("$HB" run --policy llm --model "$HBM" --base-url "$OLLAMA_URL/v1" --tools rich --horizon 20 \
        --seeds 1 --split dev --name retest-smoke --variant ctx_rule,tool_hint,guard --overwrite --no-think 2>&1)" \
        || fail "smoke run: $(echo "$smoke_out" | tail -3)"
  echo "$smoke_out"
  case "$smoke_out" in *abort:llm_errors*) fail "smoke run: the model calls failed (see log)" ;; esac

  local seeds="${HB_SEEDS:-10}" cell variant
  for cell in ${HB_CELLS:-base guard tool ctx all}; do
    variant="$(variant_of "$cell")" || fail "unknown cell $cell"
    status_file "running" "Cell: retest-$cell (${variant:-no lever}), $seeds eval seeds, horizon 60, rich tools"
    publish "Retest: status"
    log "cell retest-$cell starts (variant: ${variant:-none})"
    if [ -n "$variant" ]; then
      "$HB" run --policy llm --model "$HBM" --base-url "$OLLAMA_URL/v1" --tools rich --horizon 60 \
            --seeds "$seeds" --split eval --name "retest-$cell" --variant "$variant" --no-think || fail "cell retest-$cell"
    else
      "$HB" run --policy llm --model "$HBM" --base-url "$OLLAMA_URL/v1" --tools rich --horizon 60 \
            --seeds "$seeds" --split eval --name "retest-$cell" --no-think || fail "cell retest-$cell"
    fi
    summarize || log "WARN: summary failed after retest-$cell (the runs are stored; rerun scripts/retest_summary.py)"
    CELLS_DONE="${CELLS_DONE:+$CELLS_DONE, }$cell"
    status_file "running" "Finished retest-$cell. Summary: $OUT/summary.md"
    publish "Retest: cell $cell done ($MODEL, $seeds eval seeds, horizon 60)"
  done

  status_file "done" "All cells finished. Summary: $OUT/summary.md · walkthrough: $OUT/walkthrough-eval00$WALK_INDEX.md"
  publish "Retest: done ($MODEL)"
  osascript -e 'display notification "lever retest finished and pushed" with title "horizon-bench retest"' >/dev/null 2>&1
  log "==== done ===="
  rm -f "$LOG_DIR/retest.pid"
}

if [ "${1:-}" = "--pipeline" ]; then
  pipeline
else
  launch
fi
