#!/usr/bin/env bash
# Self-mirror direct A/B: candidate deck (A) vs current deck (B), both champion MCTS @0.8s.
set -euo pipefail
cd "$(dirname "$0")/../../.."   # -> worktree root
CFG='{"max_root_actions":6,"max_tree_depth":1,"rollout_turns":100,"rollout_depth":200,"n_worlds":4,"time_budget_s":0.8,"deviate_margin":0.1,"eval_weights":{"deck_low":-0.2,"deck_low_at":14,"deck_low_prize_gate":3}}'
PHASE="$1"; N="$2"; shift 2   # remaining args: label:deckpath:seed ...
run_shard(){
  local spec="$1"; local label="${spec%%:*}"; local rest="${spec#*:}"
  local deck="${rest%%:*}"; local seed="${rest##*:}"
  local out="eval/results/sot2284/${PHASE}_${label}_s${seed}.json"
  python3 eval/bench.py --agent-a mcts --agent-b mcts --n "$N" --seed "$seed" \
    --deck "$deck" --deck-b deck.csv --config-a "$CFG" --config-b "$CFG" \
    --json "$out" >"eval/results/sot2284/${PHASE}_${label}_s${seed}.log" 2>&1
  echo "DONE $out"
}
export -f run_shard; export PHASE N CFG
printf '%s\n' "$@" | xargs -P 12 -I{} bash -c 'run_shard "$@"' _ {}
echo "ALL_SHARDS_DONE phase=$PHASE"
