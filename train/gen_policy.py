"""Expert-iteration self-play recorder (SOT-1916).

Plays champion-MCTS self-play and records, at every SINGLE-SELECT root decision,
the tuple the learned action prior is trained on (SOT-1911 hypothesis 1):

    {"s":  [20 state features]              # value_features.extract, actor POV
     "opts":[[option_type, greedy_score]..] # one per considered root option
     "pi": [visit_share, ...]               # MCTS root visit distribution (π)
     "z":  win-label in {1.0, 0.5, 0.0}}    # value target for the acting side

`s` + each `opts[k]` reconstruct the policy net's per-option input
(agents/policy_features.option_input); `pi` is the cross-entropy target; `z`
feeds the value head / an on-policy value net. The champion planner exposes the
per-option aggregate visits via `record_root` (agents/planner.py); this recorder
never simulates rules itself.

Sharding / wall-clock cap mirror train/gen_selfplay.py (SOT-1865): `--n-shards`
/ `--shard-index` split the match space disjointly by seed, `--time-limit-s`
caps a shard so 24 cores fill a wall-clock budget. Generation uses the CHAMPION
config (no learned prior) so π is the champion's own search distribution.

Usage (from the repo root):
    python3 train/gen_policy.py --n 2000 --seed 19160101 \
        --config '{"time_budget_s":0.15,...champion...}' \
        --n-shards 24 --shard-index 0 --time-limit-s 1200 \
        --out train/data/policy.shard0.jsonl
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)  # libcg.so & deck.csv resolve relative to the repo root

from cg import game
from agents import make_agent
from agents.observation import adapt
from agents.rng import Rng
from agents.policy_features import (POLICY_FEATURE_VERSION, extract,
                                    option_feature)
from agents.actions import count_bounds

MAX_DECISIONS = 100000


def load_deck(path: str) -> list:
    with open(path) as f:
        return [int(x) for x in f.read().split("\n")[:60]]


def label_for(result: int, actor: int):
    if result == actor:
        return 1.0
    if result == 1 - actor:
        return 0.0
    if result == 2:
        return 0.5
    return None


def play_and_record(agent0, agent1, max_per_match: int):
    """One match. Returns (samples, result). Each sample is
    (state, opts, pi, actor) captured at single-select root decisions where the
    planner recorded a visit distribution."""
    obs, start = game.battle_start(agent0._deck, agent1._deck)
    if obs is None:
        raise RuntimeError(
            f"battle_start failed: errorPlayer={start.errorPlayer} "
            f"errorType={start.errorType}")
    samples = []
    try:
        decisions = 0
        while decisions < MAX_DECISIONS:
            current = obs.get("current") or {}
            result = current.get("result", -1)
            if result != -1:
                return samples, result
            actor = current.get("yourIndex", 0)
            agent = agent0 if actor == 0 else agent1
            planner = agent.planner
            # Snapshot the decision BEFORE acting: the learned prior's features
            # are state + per-option greedy score + option type.
            captured = None
            if len(samples) < max_per_match:
                view = adapt(obs)
                sel = view.select
                if sel is not None:
                    lo, hi = count_bounds(sel)
                    if lo == hi == 1 and len(sel.options) > 1:
                        gscores = planner._prior_agent.score_options(view)
                        cards = planner._prior_agent.cards
                        blocks = [option_feature(view, sel.options[i],
                                                 gscores[i], cards)
                                  for i in range(len(sel.options))]
                        captured = (extract(obs, actor), blocks, actor)
            try:
                action = agent.act(obs)
                obs = game.battle_select(action)
            except Exception:
                return samples, -1  # fault: drop the match's labels
            rec = getattr(planner, "last_root", None)
            if captured is not None and rec and rec.get("opt_visits"):
                state, blocks, act = captured
                ov = rec["opt_visits"]
                picked = list(ov.keys())
                visits = [ov[i] for i in picked]
                tot = sum(visits)
                if tot > 0 and len(picked) >= 2:
                    opts = [blocks[i] for i in picked]
                    pi = [v / tot for v in visits]
                    samples.append((state, opts, pi, act))
            decisions += 1
        return samples, -1
    finally:
        game.battle_finish()


def generate(n, seed, deck_path, config, max_per_match,
             n_shards, shard_index, time_limit_s):
    deck = load_deck(deck_path)
    base = Rng(seed)
    rows = []
    faults = 0
    played = 0
    stopped_early = False
    t0 = time.perf_counter()
    for i in range(n):
        if n_shards > 1 and i % n_shards != shard_index:
            continue
        if time_limit_s and (time.perf_counter() - t0) >= time_limit_s:
            stopped_early = True
            break
        seed_a = base.child(f"m{i}.a").seed
        seed_b = base.child(f"m{i}.b").seed
        a = make_agent("mcts", seed=seed_a, deck=deck, **config)
        b = make_agent("mcts", seed=seed_b, deck=deck, **config)
        p0, p1 = (a, b) if i % 2 == 0 else (b, a)
        samples, result = play_and_record(p0, p1, max_per_match)
        played += 1
        if result not in (0, 1, 2):
            faults += 1
            continue
        for state, opts, pi, actor in samples:
            z = label_for(result, actor)
            if z is not None:
                rows.append({"s": state, "opts": opts, "pi": pi, "z": z})
        if played % 25 == 0:
            print(f"  shard {shard_index}/{n_shards}: {played} matches, "
                  f"{len(rows)} samples, {time.perf_counter() - t0:.0f}s",
                  flush=True)
    return rows, faults, played, stopped_early, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=19160101)
    ap.add_argument("--deck", default="deck.csv")
    ap.add_argument("--max-per-match", type=int, default=60)
    ap.add_argument("--config", default=None, help="JSON MctsAgent kwargs "
                    "(champion config; record_root is forced on)")
    ap.add_argument("--n-shards", type=int, default=1)
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--time-limit-s", type=float, default=0.0)
    ap.add_argument("--out", default="train/data/policy.jsonl")
    args = ap.parse_args()

    if not (0 <= args.shard_index < max(1, args.n_shards)):
        raise SystemExit(f"shard_index {args.shard_index} out of range")

    config = json.loads(args.config) if args.config else {}
    config.pop("learned_prior_path", None)  # generate with the champion prior
    config["record_root"] = True
    print(f"GENPOL: n={args.n} seed={args.seed} shard={args.shard_index}/"
          f"{args.n_shards} time_limit_s={args.time_limit_s} config={config}",
          flush=True)
    rows, faults, played, stopped_early, secs = generate(
        args.n, args.seed, args.deck, config, args.max_per_match,
        args.n_shards, args.shard_index, args.time_limit_s)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(json.dumps({"meta": {
            "policy_feature_version": POLICY_FEATURE_VERSION,
            "n_matches": args.n, "seed": args.seed, "config": config,
            "n_shards": args.n_shards, "shard_index": args.shard_index,
            "matches_played": played, "stopped_early": stopped_early,
            "gen_seconds": round(secs, 1), "faults": faults,
            "samples": len(rows)}}) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} policy samples, faults={faults} "
          f"matches_played={played} gen_seconds={secs:.0f} -> {args.out}")


if __name__ == "__main__":
    main()
