#!/bin/bash
# One command on a Mac runs the real-model experiment end to end and pushes the results:
#
#   curl -fsSL https://raw.githubusercontent.com/langju123456/horizon-bench/main/scripts/mac_llm_run.sh | bash
#
# What it does, unattended (the Terminal window can be closed once it says "started"):
#   1. finds Python >= 3.11 and Ollama (installs them with Homebrew if missing)
#   2. clones or updates ~/code/horizon-bench and installs it into .venv
#   3. pulls the model (qwen3:8b, or qwen3:4b on Macs with less than 16 GB) and makes a variant with a 16k context
#   4. runs the scripted baseline on this Mac's own eval salt (batch mac-baseline, about 30 s)
#   5. smoke-tests the LLM agent on one public dev seed
#   6. runs the LLM on the eval seeds, horizon 60 first, then 120 (bare and rich tools)
#   7. after every phase: writes reports/, reports/mac-run/STATUS.md, commits and pushes
# The Mac is kept awake with caffeinate. Keep the lid open and the charger in.
# Overrides: HB_MODEL=qwen3:4b, HB_SEEDS=10, HB_THINK=1 (leave Qwen3 thinking on).
# Written for the stock macOS bash 3.2.

set -uo pipefail
# Local calls must not go through a desktop proxy (Clash and the like answer localhost with 502).
export NO_PROXY="localhost,127.0.0.1,::1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"
OLLAMA_URL="http://127.0.0.1:11434"

REPO_URL="https://github.com/langju123456/horizon-bench.git"
DIR="${HB_DIR:-$HOME/code/horizon-bench}"
LOG_DIR="$HOME/.horizon-bench"
LOG="$LOG_DIR/mac_run.log"

launch() {
  mkdir -p "$LOG_DIR" "$(dirname "$DIR")"
  if [ -d "$DIR/.git" ]; then
    git -C "$DIR" pull --ff-only -q || { echo "git pull failed in $DIR"; exit 1; }
  else
    git clone -q "$REPO_URL" "$DIR" || { echo "git clone failed"; exit 1; }
  fi
  if [ -f "$LOG_DIR/pid" ] && kill -0 "$(cat "$LOG_DIR/pid")" 2>/dev/null; then
    echo "already running (pid $(cat "$LOG_DIR/pid")); log: $LOG"
    exit 0
  fi
  nohup caffeinate -ims /bin/bash "$DIR/scripts/mac_llm_run.sh" --pipeline >>"$LOG" 2>&1 &
  echo $! >"$LOG_DIR/pid"
  echo "started in the background (pid $!). You can close this window."
  echo "log: $LOG"
}

# ---------------------------------------------------------------------------------------------
log() { echo "[$(date '+%m-%d %H:%M:%S')] $*"; }

PHASES_DONE=""
status_file() {
  local state="$1" detail="$2"
  mkdir -p "$DIR/reports/mac-run"
  {
    echo "# Mac run status"
    echo
    echo "- state: **$state**"
    echo "- updated: $(date '+%Y-%m-%d %H:%M %Z')"
    echo "- machine: $(sysctl -n hw.model 2>/dev/null), $(($(sysctl -n hw.memsize) / 1073741824)) GB, macOS $(sw_vers -productVersion 2>/dev/null)"
    echo "- ollama: $("${OLLAMA:-ollama}" --version 2>/dev/null | tail -1)"
    echo "- model: ${MODEL:-?} (as ${HBM:-?}, num_ctx 16384), thinking: ${THINK_LABEL:-?}"
    echo "- eval salt sha256: ${SALT_HASH:-?}"
    echo "- phases done: ${PHASES_DONE:-none}"
    echo
    echo "$detail"
    echo
    echo '## Last 40 log lines'
    echo
    echo '```'
    tail -n 40 "$LOG" 2>/dev/null
    echo '```'
  } >"$DIR/reports/mac-run/STATUS.md"
}

publish() {
  local msg="$1"
  cd "$DIR" || return 1
  git add reports/ >/dev/null 2>&1
  if git diff --cached --quiet; then return 0; fi
  git -c user.name="Lang Ju" -c user.email="langju123456@gmail.com" commit -q -m "$msg"
  git pull --rebase -q || log "WARN: git pull --rebase failed"
  if git push -q; then log "pushed: $msg"; else log "WARN: push failed (results stay in $DIR/reports)"; fi
}

fail() {
  log "FAILED: $1"
  status_file "failed" "Stopped at: $1"
  publish "Mac run: failed at $1"
  osascript -e "display notification \"stopped: $1\" with title \"horizon-bench\"" >/dev/null 2>&1
  rm -f "$LOG_DIR/pid"
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

find_brew() {
  local c
  for c in brew /opt/homebrew/bin/brew "$HOME/.homebrew/bin/brew" /usr/local/bin/brew; do
    if command -v "$c" >/dev/null 2>&1; then command -v "$c"; return 0; fi
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

pipeline() {
  OLLAMA=""; MODEL=""; HBM=""; THINK_LABEL=""; SALT_HASH=""
  cd "$DIR" || fail "repo directory missing"
  log "==== horizon-bench Mac run starts ($(git rev-parse --short HEAD)) ===="
  BREW="$(find_brew || true)"

  PY="$(find_python || true)"
  if [ -z "$PY" ] && [ -n "$BREW" ]; then log "installing python@3.12 with Homebrew"; "$BREW" install -q python@3.12; PY="$(find_python || true)"; fi
  [ -n "$PY" ] || fail "no Python >= 3.11 (install it from python.org or Homebrew)"
  log "python: $PY ($("$PY" --version 2>&1))"

  OLLAMA="$(find_ollama || true)"
  if [ -z "$OLLAMA" ] && [ -n "$BREW" ]; then log "installing ollama with Homebrew"; "$BREW" install -q ollama; OLLAMA="$(find_ollama || true)"; fi
  [ -n "$OLLAMA" ] || fail "ollama not found (install it from ollama.com)"
  if ! curl -sf --noproxy '*' $OLLAMA_URL/api/tags >/dev/null; then
    log "starting ollama serve"
    nohup "$OLLAMA" serve >>"$LOG_DIR/ollama.log" 2>&1 &
    for _ in $(seq 1 60); do curl -sf --noproxy '*' $OLLAMA_URL/api/tags >/dev/null && break; sleep 1; done
  fi
  curl -sf --noproxy '*' $OLLAMA_URL/api/tags >/dev/null || fail "ollama server did not come up"

  local mem_gb
  mem_gb=$(($(sysctl -n hw.memsize) / 1073741824))
  if [ -n "${HB_MODEL:-}" ]; then MODEL="$HB_MODEL"; elif [ "$mem_gb" -ge 15 ]; then MODEL="qwen3:8b"; else MODEL="qwen3:4b"; fi
  TAG="$(echo "$MODEL" | tr ':./' '---')"
  HBM="hb-$TAG"
  if [ "${HB_THINK:-0}" = "1" ]; then THINK_FLAG=""; THINK_LABEL="on"; BATCH="$TAG"; else THINK_FLAG="--no-think"; THINK_LABEL="off (/no_think)"; BATCH="$TAG-nothink"; fi
  log "memory ${mem_gb} GB -> model $MODEL, thinking $THINK_LABEL, batch $BATCH"
  "$OLLAMA" pull "$MODEL" || fail "ollama pull $MODEL"
  printf 'FROM %s\nPARAMETER num_ctx 16384\n' "$MODEL" >"$LOG_DIR/Modelfile"
  "$OLLAMA" create "$HBM" -f "$LOG_DIR/Modelfile" >/dev/null || fail "ollama create $HBM"

  if [ ! -x .venv/bin/hb ]; then
    "$PY" -m venv .venv || fail "python venv"
  fi
  .venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1
  .venv/bin/python -m pip install -q -e . || fail "pip install"
  HB=".venv/bin/hb"
  .venv/bin/python -c 'from horizon_bench.spec import load_salt' || fail "package import"
  SALT_HASH="$(.venv/bin/python -c 'from horizon_bench.spec import load_salt, salt_hash; print(salt_hash(load_salt()))')"
  log "eval salt sha256 $SALT_HASH (salt stays in $DIR/.hb, never committed)"
  status_file "running" "Phase: scripted baseline"

  # Scripted baseline on this Mac's salt, so the LLM rows below share its eval seeds.
  "$HB" run --policy pid,naive,lazy,random --tools bare,rich --horizon 60,120,240 --seeds 20 \
        --split eval --name mac-baseline | tail -n 1 || fail "scripted baseline"
  "$HB" report --name mac-baseline >/dev/null || fail "baseline report"
  PHASES_DONE="baseline"
  status_file "running" "Phase: LLM smoke test"
  publish "Mac run: scripted baseline on this Mac's eval salt"

  # Preflight: one chat call straight to Ollama, so a failure shows Ollama's own answer in the log.
  local pre
  pre="$(curl -sS --noproxy '*' -m 600 "$OLLAMA_URL/v1/chat/completions" -H 'Content-Type: application/json' \
        -d "{\"model\": \"$HBM\", \"messages\": [{\"role\": \"user\", \"content\": \"Reply with OK. /no_think\"}], \"max_tokens\": 20}" 2>&1)"
  echo "preflight: $(echo "$pre" | head -c 400)"
  case "$pre" in *'"choices"'*) ;; *) fail "Ollama preflight call failed: $(echo "$pre" | head -c 200)" ;; esac

  # Smoke: one public dev seed, 60 steps.
  local smoke_out
  smoke_out="$("$HB" run --policy llm --model "$HBM" --base-url "$OLLAMA_URL/v1" --tools rich --horizon 60 \
        --seeds 1 --split dev --name "smoke-$BATCH" --overwrite $THINK_FLAG 2>&1)" || fail "LLM smoke run"
  echo "$smoke_out"
  case "$smoke_out" in *abort:llm_errors*) fail "LLM smoke: the model calls failed (see log)" ;; esac
  PHASES_DONE="baseline, smoke"

  local seeds="${HB_SEEDS:-10}"
  for h in 60 120; do
    status_file "running" "Phase: LLM, horizon $h, bare and rich, $seeds eval seeds each"
    publish "Mac run: status"
    log "LLM phase: horizon $h"
    "$HB" run --policy llm --model "$HBM" --base-url "$OLLAMA_URL/v1" --tools rich,bare --horizon "$h" \
          --seeds "$seeds" --split eval \
          --name "$BATCH" $THINK_FLAG || fail "LLM run at horizon $h"
    "$HB" report --name llm-vs-baseline --batch mac-baseline --batch "$BATCH" >/dev/null || fail "report after horizon $h"
    PHASES_DONE="$PHASES_DONE, llm h$h"
    status_file "running" "Finished horizon $h."
    publish "Mac run: $MODEL at horizon $h (bare and rich, $seeds eval seeds)"
  done

  status_file "done" "All phases finished. Report: reports/llm-vs-baseline/report.md"
  publish "Mac run: done ($MODEL)"
  osascript -e 'display notification "real-model run finished and pushed" with title "horizon-bench"' >/dev/null 2>&1
  log "==== done ===="
  rm -f "$LOG_DIR/pid"
}

if [ "${1:-}" = "--pipeline" ]; then
  pipeline
else
  launch
fi
