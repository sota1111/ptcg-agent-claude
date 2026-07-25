"""Expert-iteration self-play data generation (SOT-1914).

Plays champion-MCTS mirror self-play and records, at every decision state with a
real choice, the triple the SOT-1911 expert iteration needs:

    (state features, MCTS root visit distribution, final win/loss label)

plus the SOT-1894 **H1-H3 board-risk features** and an **auxiliary early-warning
target** ("does the acting side go on to lose by board-wipe / seed-depletion
within N of its own decisions").

Each recorded row is one JSON object::

    {"m": match, "actor": 0|1, "d": side_decision_ordinal,
     "f": [state features],            # agents.value_features.extract
     "h": [H1-H3 features],            # agents.expert_features.extract_h
     "pi": {"a": [[opt idx], ...], "v": [visits...], "p": [probs...]},
     "y": 1.0|0.0|0.5,                 # win / loss / draw for the acting side
     "aux_wipe": 0|1, "aux_seed": 0|1}

``pi.p`` is the visit distribution over the root candidate ACTIONS (each action
is a list of option indices — a single index for pick-one selects, a set for
count selects), normalized to sum 1. Only states with >=2 real candidates and a
searched root are recorded (forced / degraded / greedy-fallback decisions carry
no policy signal).

**champion is unchanged.** The default agent config is ``main.FABLE_CONFIG``; the
planner change this issue adds is diagnostic-only (it publishes the root visit
counts into ``planner.last_stats`` without touching the chosen action). Data
generation only READS matches.

Sharding + resume (SOT-1865 pattern, extended for restart safety):
- ``--n-shards M --shard-index k`` plays only the global match indices
  ``i % M == k`` (disjoint union across shards → one coherent run), so an
  expensive champion generation can be split across CPU cores/processes.
- Output is append-only JSONL with a ``{"match_done": i}`` marker after each
  match's rows. On restart the generator scans the existing file, SKIPS already
  completed matches, and appends the rest — an interrupted shard resumes without
  redoing or duplicating work. Rows of a match with no ``match_done`` marker
  (crash mid-match) are dropped by the reader, so partial writes never corrupt
  the dataset. Cumulative throughput meta is written to ``<out>.meta.json``.

Usage (from the repo root)::

    python3 train/gen_expert_data.py --n 200 --seed 20260725 \
        --out train/data/expert.shard0.jsonl \
        --n-shards 8 --shard-index 0 [--time-limit-s 28800] [--config '{...}']
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
from agents.rng import Rng
from agents.cards import shared_index
from agents.value_features import FEATURE_VERSION, extract
from agents.expert_features import (H_FEATURE_VERSION, extract_h, loss_cause)

try:  # champion config is the single source of truth (main.py)
    from main import FABLE_CONFIG
except Exception:  # pragma: no cover - keep a copy if main import is unavailable
    FABLE_CONFIG = {
        "max_root_actions": 6, "max_tree_depth": 1, "rollout_turns": 100,
        "rollout_depth": 200, "n_worlds": 4, "time_budget_s": 0.8,
        "deviate_margin": 0.1,
        "eval_weights": {"deck_low": -0.2, "deck_low_at": 14,
                         "deck_low_prize_gate": 3}}

SCHEMA_VERSION = 1
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
    return None  # unfinished / unknown


def _visit_distribution(agent):
    """Root visit distribution from the acting MCTS agent's last decision, or
    None when the decision carried no policy signal (forced/degraded/non-MCTS,
    or a single candidate)."""
    planner = getattr(agent, "_planner", None)
    stats = getattr(planner, "last_stats", None) if planner else None
    if not stats:
        return None
    acts = stats.get("root_actions")
    vis = stats.get("root_visits")
    if not acts or not vis or len(acts) < 2:
        return None
    total = sum(vis)
    if total <= 0:
        return None
    probs = [v / total for v in vis]
    return {"a": [list(a) for a in acts], "v": list(vis), "p": probs}


def play_and_record(agent0, agent1, card_index, stride: int,
                    max_per_match: int, aux_horizon: int):
    """Play one match; return (rows, result). Rows carry per-sample features,
    the visit distribution, and (post-match) y / aux labels."""
    obs, start = game.battle_start(agent0._deck, agent1._deck)
    if obs is None:
        raise RuntimeError(
            f"battle_start failed: errorPlayer={start.errorPlayer} "
            f"errorType={start.errorType}")
    samples = []
    side_decisions = [0, 0]
    last_obs = obs
    try:
        decisions = 0
        while decisions < MAX_DECISIONS:
            current = obs.get("current") or {}
            result = current.get("result", -1)
            if result != -1:
                last_obs = obs
                break
            actor = current.get("yourIndex", 0)
            agent = agent0 if actor == 0 else agent1
            record = (decisions % max(1, stride) == 0
                      and len(samples) < max_per_match)
            # Snapshot features BEFORE acting (the state the policy is asked
            # about); read the visit distribution AFTER acting.
            feats = extract(obs, actor) if record else None
            hfeats = extract_h(obs, actor, card_index) if record else None
            side_ord = side_decisions[actor]
            try:
                action = agent.act(obs)
            except Exception:
                return samples, -1, last_obs  # fault: drop the match
            if record:
                pi = _visit_distribution(agent)
                if pi is not None:  # only states with a real searched choice
                    samples.append({"actor": actor, "d": side_ord,
                                    "f": feats, "h": hfeats, "pi": pi})
            side_decisions[actor] += 1
            obs = game.battle_select(action)
            last_obs = obs
            decisions += 1
        else:
            return samples, -1, last_obs
    finally:
        game.battle_finish()

    # Post-match labelling.
    if result not in (0, 1, 2):
        return samples, -1, last_obs
    loser = 1 - result if result in (0, 1) else None
    tags = (loss_cause(last_obs, loser, card_index)
            if loser is not None else {"wipe": 0, "seed": 0})
    final_ord = side_decisions
    for s in samples:
        s["y"] = label_for(result, s["actor"])
        near_loss = (loser is not None and s["actor"] == loser
                     and (final_ord[loser] - s["d"]) <= aux_horizon)
        s["aux_wipe"] = tags["wipe"] if near_loss else 0
        s["aux_seed"] = tags["seed"] if near_loss else 0
    samples = [s for s in samples if s["y"] is not None]
    return samples, result, last_obs


# --- resumable shard I/O ------------------------------------------------------

def scan_completed(path: str) -> set:
    """Match indices already fully recorded in an existing shard file."""
    done = set()
    if not os.path.exists(path):
        return done
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and "match_done" in obj:
                done.add(int(obj["match_done"]))
    return done


def read_expert_rows(path: str):
    """Read a shard's sample rows, dropping any match with no ``match_done``
    marker (an interrupted mid-match write). Returns (rows, completed set)."""
    by_match = {}
    completed = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "match_done" in obj:
                completed.add(int(obj["match_done"]))
            elif "m" in obj:
                by_match.setdefault(obj["m"], []).append(obj)
    rows = []
    for m, group in by_match.items():
        if m in completed:
            rows.extend(group)
    return rows, completed


def generate(agent_name, n, seed, deck_path, stride, max_per_match,
             aux_horizon, out, config=None, n_shards=1, shard_index=0,
             time_limit_s=0.0):
    deck = load_deck(deck_path)
    card_index = shared_index()
    base = Rng(seed)
    cfg = FABLE_CONFIG if config is None else config
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    already = scan_completed(out)
    played = 0
    faults = 0
    assigned = 0
    resumed = len(already)
    new_samples = 0
    stopped_early = False
    t0 = time.perf_counter()
    with open(out, "a") as f:
        for i in range(n):
            if n_shards > 1 and i % n_shards != shard_index:
                continue
            assigned += 1
            if i in already:
                continue  # resume: already recorded
            if time_limit_s and (time.perf_counter() - t0) >= time_limit_s:
                stopped_early = True
                break
            seed_a = base.child(f"m{i}.a").seed
            seed_b = base.child(f"m{i}.b").seed
            a = make_agent(agent_name, seed=seed_a, deck=deck, **cfg)
            b = make_agent(agent_name, seed=seed_b, deck=deck, **cfg)
            p0, p1 = (a, b) if i % 2 == 0 else (b, a)
            samples, result, _ = play_and_record(
                p0, p1, card_index, stride, max_per_match, aux_horizon)
            played += 1
            if result not in (0, 1, 2):
                faults += 1
                continue
            for s in samples:
                s["m"] = i
                f.write(json.dumps(s) + "\n")
            f.write(json.dumps({"match_done": i}) + "\n")
            f.flush()
            new_samples += len(samples)
            if played % 25 == 0:
                el = time.perf_counter() - t0
                print(f"  shard {shard_index}/{n_shards}: {played} played, "
                      f"{new_samples} new samples, {el:.0f}s "
                      f"({played / el * 3600:.0f} games/h)", flush=True)

    gen_seconds = time.perf_counter() - t0
    meta = {
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "h_feature_version": H_FEATURE_VERSION,
        "agent": agent_name, "seed": seed, "config": cfg,
        "n_matches": n, "n_shards": n_shards, "shard_index": shard_index,
        "stride": stride, "aux_horizon": aux_horizon,
        "matches_played": played, "matches_resumed": resumed,
        "faults": faults, "new_samples": new_samples,
        "stopped_early": stopped_early,
        "gen_seconds": round(gen_seconds, 1),
        "games_per_hour": round(played / gen_seconds * 3600, 1)
        if gen_seconds > 0 else 0.0,
    }
    with open(out + ".meta.json", "w") as mf:
        json.dump(meta, mf, indent=2)
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--agent", default="mcts",
                    help="both players (mirror self-play); champion is 'mcts'")
    ap.add_argument("--seed", type=int, default=20260725)
    ap.add_argument("--deck", default="deck.csv")
    ap.add_argument("--stride", type=int, default=1,
                    help="record every k-th decision state (default 1)")
    ap.add_argument("--max-per-match", type=int, default=200)
    ap.add_argument("--aux-horizon", type=int, default=8,
                    help="lose-within-N-own-decisions horizon for aux targets")
    ap.add_argument("--config", default=None,
                    help="JSON agent kwargs (default: champion FABLE_CONFIG)")
    ap.add_argument("--n-shards", type=int, default=1)
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--time-limit-s", type=float, default=0.0,
                    help="stop this shard after this many wall-clock seconds")
    ap.add_argument("--out", default="train/data/expert.jsonl")
    args = ap.parse_args()

    if not (0 <= args.shard_index < max(1, args.n_shards)):
        raise SystemExit(f"shard_index {args.shard_index} out of range for "
                         f"n_shards {args.n_shards}")
    config = json.loads(args.config) if args.config else None
    print(f"GEN-EXPERT: agent={args.agent} n={args.n} seed={args.seed} "
          f"stride={args.stride} shard={args.shard_index}/{args.n_shards} "
          f"time_limit_s={args.time_limit_s} "
          f"config={'FABLE_CONFIG' if config is None else config}", flush=True)
    meta = generate(args.agent, args.n, args.seed, args.deck, args.stride,
                    args.max_per_match, args.aux_horizon, args.out,
                    config=config, n_shards=args.n_shards,
                    shard_index=args.shard_index,
                    time_limit_s=args.time_limit_s)
    print(f"wrote shard -> {args.out}: {meta['new_samples']} new samples, "
          f"matches_played={meta['matches_played']} "
          f"resumed={meta['matches_resumed']} faults={meta['faults']} "
          f"gen_seconds={meta['gen_seconds']:.0f} "
          f"games_per_hour={meta['games_per_hour']}")


if __name__ == "__main__":
    main()
