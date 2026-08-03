#!/usr/bin/env bash
# SOT-2335 defensive-lever A/B on the ELO-proxy gauntlet (SOT-2334).
# Base = champion (FABLE_CONFIG); Cand = champion + board-wipe insurance
# (bench_dev / bench_dev_cap / evo_ready). Run serially for a fair
# wall-clock MCTS budget. Seeds are independent; seed[0] doubles as screen.
set -euo pipefail
cd "$(dirname "$0")/../.."
SEEDS="2335,20335,42335"
N=16
BUD=0.12
LEVER='{"bench_dev":0.4,"bench_dev_cap":2,"evo_ready":0.2}'
BASE=docs/elo_gauntlet/sot2335_base.jsonl
CAND=docs/elo_gauntlet/sot2335_cand.jsonl
rm -f "$BASE" "$CAND"

echo "=== BASE (champion) ==="
python3 -m eval.elo_gauntlet run --seeds "$SEEDS" --n "$N" \
  --champion-budget "$BUD" --out "$BASE"

echo "=== CAND (defensive lever) ==="
python3 -m eval.elo_gauntlet run --seeds "$SEEDS" --n "$N" \
  --champion-budget "$BUD" --champion-eval-weights "$LEVER" --out "$CAND"

echo "=== SUMMARY BASE ==="
python3 -m eval.elo_gauntlet summary "$BASE"
echo "=== SUMMARY CAND ==="
python3 -m eval.elo_gauntlet summary "$CAND"
echo "AB_DONE"
