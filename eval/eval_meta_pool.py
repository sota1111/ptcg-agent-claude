#!/usr/bin/env python3
"""Evaluate the meta active pool against representative meta decks (SOT-2055).

Each deck in the active pool (``decks/meta_active/manifest.json``) is piloted by
the same agent and played, seat-alternating over several seeds, against a small
set of *representative* meta decks:

* the current max-share deck (マリィのオーロンゲex — Marnie's Grimmsnarl ex),
* the #2 archetype (フーディン — Alakazam),
* the leaderboard-leading / low-usage deck (タケルライコex — Raging Bolt).

The agent is ``greedy`` by default: it is deterministic per injected seed, fast
enough to screen the whole pool in one run, and already a first-class baseline in
this repo (``eval/bench.py``). The engine RNG is not seedable (ASSUMPTIONS A-9),
so win rates are statistical — we report Wilson 95% CIs. This is a *screen* that
confirms every active deck loads, is legal to the engine, and produces recorded
head-to-head results, exactly what SOT-2055's acceptance asks for.

    venv/bin/python eval/eval_meta_pool.py --matches 8 --seed 0 \
        --json eval/results/sot2050/pool_vs_representatives.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

ACTIVE_MANIFEST = os.path.join(REPO, "decks", "meta_active", "manifest.json")

# Representative opponents by deck filename + role label + source group.
# Labels are ASCII (the forbidden-term linter scans eval/) — the archetype each
# stands for is documented in the module docstring and the manifest.
REPRESENTATIVES = [
    ("15_marnie_s_grimmsnarl_ex.csv", "max-share-meta", "candidates"),
    ("12_alakazam_dudunsparce.csv", "second-meta", "candidates"),
    ("02_raging_bolt_ogerpon.csv", "board-leader", "candidates"),
]


def deck_path(fname: str, group: str) -> str:
    return os.path.join(REPO, "decks", group, fname)


def load_active(manifest_path: str):
    with open(manifest_path, encoding="utf-8") as f:
        m = json.load(f)
    return [(d["file"], d.get("source_group", "candidates"), d.get("archetype", d["file"]))
            for d in m["decks"]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=ACTIVE_MANIFEST)
    ap.add_argument("--agent", default="greedy")
    ap.add_argument("--matches", type=int, default=8,
                    help="matches per (deck, representative) pairing")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    os.chdir(REPO)
    from eval.bench import play_match, load_deck, wilson_ci
    from agents import make_agent
    from agents.rng import Rng

    active = load_active(args.manifest)
    reps = [(f, label, load_deck(deck_path(f, g)))
            for (f, label, g) in REPRESENTATIVES]
    base = Rng(args.seed)

    results = []
    t0 = time.time()
    total_faults = 0
    for fname, group, archetype in active:
        deck = load_deck(deck_path(fname, group))
        per_rep = []
        wins_all = losses_all = draws_all = faults_all = decisions_all = 0
        for rep_file, rep_label, rep_deck in reps:
            wins = losses = draws = faults = decisions = 0
            for i in range(args.matches):
                seed_a = base.child(f"{fname}.{rep_file}.{i}.a").seed
                seed_b = base.child(f"{fname}.{rep_file}.{i}.b").seed
                a = make_agent(args.agent, seed=seed_a, deck=deck)
                b = make_agent(args.agent, seed=seed_b, deck=rep_deck)
                a_first = (i % 2 == 0)
                p0, p1 = (a, b) if a_first else (b, a)
                result, dec, reject, exc = play_match(p0, p1)
                decisions += dec
                if reject or exc:
                    faults += 1
                    losses += 1        # a fault is charged as a loss for the pool deck
                    continue
                if result == 2:
                    draws += 1
                elif result in (0, 1):
                    a_won = (result == 0) == a_first
                    wins += 1 if a_won else 0
                    losses += 0 if a_won else 1
                else:
                    faults += 1
            decided = wins + losses
            lo, hi = wilson_ci(wins, decided)
            per_rep.append({
                "representative": rep_file, "label": rep_label,
                "matches": args.matches, "wins": wins, "losses": losses,
                "draws": draws, "faults": faults,
                "win_rate": round(wins / decided, 3) if decided else None,
                "ci95": [round(lo, 3), round(hi, 3)],
            })
            wins_all += wins
            losses_all += losses
            draws_all += draws
            faults_all += faults
            decisions_all += decisions
        decided_all = wins_all + losses_all
        results.append({
            "deck": fname, "archetype": archetype,
            "overall_win_rate": round(wins_all / decided_all, 3) if decided_all else None,
            "wins": wins_all, "losses": losses_all, "draws": draws_all,
            "faults": faults_all,
            "vs_representatives": per_rep,
        })
        total_faults += faults_all

    summary = {
        "manifest": os.path.relpath(args.manifest, REPO),
        "agent": args.agent, "matches_per_pairing": args.matches, "seed": args.seed,
        "n_active": len(active), "representatives": [r[0] for r in reps],
        "total_faults": total_faults,
        "elapsed_s": round(time.time() - t0, 2),
        "decks": sorted(results, key=lambda r: -(r["overall_win_rate"] or 0)),
    }

    print(f"evaluated {len(active)} active decks vs {len(reps)} representatives "
          f"({args.matches} matches each) in {summary['elapsed_s']}s; "
          f"faults={total_faults}")
    for r in summary["decks"]:
        print(f"  {r['deck']:44s} overall {str(r['overall_win_rate']):>5}  "
              f"(W{r['wins']}/L{r['losses']}/D{r['draws']}/F{r['faults']})")

    if args.json:
        os.makedirs(os.path.dirname(args.json), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"wrote {os.path.relpath(args.json, REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
