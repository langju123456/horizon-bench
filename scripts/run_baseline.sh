#!/usr/bin/env bash
# Reproduces reports/baseline: scripted policies x tool modes x horizons, 20 seeds each.
# The eval split derives its seeds from a private salt (.hb/eval_salt, created on first use,
# never committed); reports/baseline/manifest.json records only its sha256.
# Without that salt, run the same thing on public seeds with: SPLIT=dev scripts/run_baseline.sh
set -euo pipefail
SPLIT="${SPLIT:-eval}"
NAME="${NAME:-baseline}"
hb run --policy pid,naive,lazy,random --tools bare,rich --horizon 60,120,240 \
       --seeds 20 --split "$SPLIT" --name "$NAME"
hb report --name "$NAME"
