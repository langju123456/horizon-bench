#!/bin/bash
# Real-model prompt-prefix-cache experiment on a Mac with Ollama, unattended, results pushed to the branch:
#
#   curl -fsSL https://raw.githubusercontent.com/langju123456/horizon-bench/feat/otel-prompt-cache/scripts/mac_cache_run.sh | bash
#
# Question: what does a trim of the rolling window cost on a local server with a prefix (KV) cache, and how does
# the window size change how often that cost is paid? Ollama reuses the KV cache of the previous prompt for the
# longest common prefix; a trim moves every kept message, so the next call recomputes almost the whole prompt.
#
# Arms, same 3 public dev seeds, rich tools, horizon 120 (HB_ARMS="budget:keep ...", default "4000:24 4000:8"):
#   4000:24  context budget 4000 estimated tokens, trim keeps the last 24 messages
#   4000:8   same budget, trim keeps the last 8: the window empties further, so trims come less often
# (At the default budget of 8000 a 40-step session never fills the window, so nothing is trimmed: batch
# cache-keep24 from the first run, kept in the report as the no-trim reference.)
# Each arm reports: prompt share reusable from the previous call, trims per run, and p50 latency and tokens to
# compute for calls that extend the previous prompt vs calls right after a trim (hb report, "Prompt prefix reuse").
#
# Uses its own checkout (~/code/horizon-bench-cache) on branch feat/otel-prompt-cache, so the main clone and its
# runs are untouched. Needs Ollama with qwen3:8b (pulled if missing) and Python >= 3.11. About 30-40 minutes on a
# MacBook Air M4. Overrides: HB_MODEL, HB_SEEDS (default 3), HB_HORIZON (default 120), HB_BRANCH.

set -uo pipefail
export NO_PROXY="localhost,127.0.0.1,::1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"
OLLAMA_URL="http://127.0.0.1:11434"
REPO_URL="https://github.com/langju123456/horizon-bench.git"
BRANCH="${HB_BRANCH:-feat/otel-prompt-cache}"
DIR="$HOME/code/horizon-bench-cache"
LOG_DIR="$HOME/.horizon-bench"
LOG="$LOG_DIR/cache_run.log"

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*"; }

launch() {
  mkdir -p "$LOG_DIR" "$(dirname "$DIR")"
  if [ -d "$DIR/.git" ]; then
    git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" checkout -q "$BRANCH" && git -C "$DIR" pull -q --rebase \
      || { echo "git update failed in $DIR"; exit 1; }
  else
    git clone -q -b "$BRANCH" "$REPO_URL" "$DIR" || { echo "git clone failed"; exit 1; }
  fi
  nohup caffeinate -ims /bin/bash "$DIR/scripts/mac_cache_run.sh" --pipeline >>"$LOG" 2>&1 &
  echo "started in the background (pid $!). You can close this window. Log: $LOG"
}

publish() {
  cd "$DIR" || return 1
  git add reports/ >/dev/null 2>&1
  git diff --cached --quiet && return 0
  git -c user.name="Lang Ju" -c user.email="langju123456@gmail.com" commit -q -m "$1"
  git pull -q --rebase || log "WARN: git pull --rebase failed"
  if git push -q origin "$BRANCH"; then log "pushed: $1"; else log "WARN: push failed (results stay in $DIR/reports)"; fi
}

status() {
  mkdir -p "$DIR/reports/mac-cache-run"
  { echo "# Prompt-cache run status"; echo; echo "- state: **$1**"; echo "- updated: $(date '+%Y-%m-%d %H:%M %Z')"
    echo "- model: ${MODEL:-?}"; echo; echo "$2"; echo; echo '```'; tail -n 30 "$LOG" 2>/dev/null; echo '```'
  } >"$DIR/reports/mac-cache-run/STATUS.md"
}

fail() { log "FAILED: $1"; status failed "Stopped at: $1"; publish "Mac cache run: failed at $1"; exit 1; }

pipeline() {
  cd "$DIR" || fail "repo directory missing"
  log "==== prompt-cache run starts ($(git rev-parse --short HEAD)) ===="
  PY=""
  for c in python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
      PY="$(command -v "$c")"; break
    fi
  done
  [ -n "$PY" ] || fail "no Python >= 3.11"
  OLLAMA=""
  for c in ollama /Applications/Ollama.app/Contents/Resources/ollama /opt/homebrew/bin/ollama /usr/local/bin/ollama; do
    if command -v "$c" >/dev/null 2>&1; then OLLAMA="$(command -v "$c")"; break; fi
  done
  [ -n "$OLLAMA" ] || fail "ollama not found"
  if ! curl -sf --noproxy '*' $OLLAMA_URL/api/tags >/dev/null; then
    nohup "$OLLAMA" serve >>"$LOG_DIR/ollama.log" 2>&1 &
    for _ in $(seq 1 60); do curl -sf --noproxy '*' $OLLAMA_URL/api/tags >/dev/null && break; sleep 1; done
  fi
  curl -sf --noproxy '*' $OLLAMA_URL/api/tags >/dev/null || fail "ollama server did not come up"

  MODEL="${HB_MODEL:-qwen3:8b}"
  HBM="hb-$(echo "$MODEL" | tr ':./' '---')"
  "$OLLAMA" pull "$MODEL" >/dev/null || fail "ollama pull $MODEL"
  printf 'FROM %s\nPARAMETER num_ctx 16384\n' "$MODEL" >"$LOG_DIR/Modelfile"
  "$OLLAMA" create "$HBM" -f "$LOG_DIR/Modelfile" >/dev/null || fail "ollama create $HBM"
  [ -x .venv/bin/hb ] || "$PY" -m venv .venv || fail "venv"
  .venv/bin/python -m pip install -q -e '.[otel]' || fail "pip install"
  HB=".venv/bin/hb"

  local seeds="${HB_SEEDS:-3}" horizon="${HB_HORIZON:-120}" batches="" arm budget keep
  for b in cache-keep24 $(for arm in ${HB_ARMS:-4000:24 4000:8}; do echo "cache-ctx${arm%%:*}-keep${arm##*:}"; done); do
    batches="$batches --batch $b"
  done
  for arm in ${HB_ARMS:-4000:24 4000:8}; do
    budget="${arm%%:*}"; keep="${arm##*:}"
    status running "Arm budget $budget, keep $keep: $seeds dev seeds, horizon $horizon"
    publish "Mac cache run: status"
    log "arm budget $budget keep $keep"
    "$HB" run --policy llm --model "$HBM" --base-url "$OLLAMA_URL/v1" --no-think --tools rich --horizon "$horizon" \
          --seeds "$seeds" --split dev --context-budget "$budget" --keep-last-messages "$keep" \
          --name "cache-ctx$budget-keep$keep" || fail "arm $arm"
    # shellcheck disable=SC2086
    "$HB" report --name prompt-cache $batches >/dev/null 2>&1 || "$HB" report --name prompt-cache --batch "cache-ctx$budget-keep$keep" >/dev/null || fail "report"
  done
  status done "All arms finished. Report: reports/prompt-cache/report.md (section: Prompt prefix reuse)"
  publish "Mac cache run: $MODEL, arms ${HB_ARMS:-4000:24 4000:8} ($seeds dev seeds, horizon $horizon)"
  osascript -e 'display notification "prompt-cache run finished and pushed" with title "horizon-bench"' >/dev/null 2>&1
  log "==== done ===="
}

if [ "${1:-}" = "--pipeline" ]; then pipeline; else launch; fi
