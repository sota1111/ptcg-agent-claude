"""Opponent-pool robustness driver (SOT-1940).

Question: is the fable/claude champion (`mcts` under `main.FABLE_CONFIG`)
overfit to the single reference opponent (greedy on the mirror deck) that the
SOT-1938 baseline measured? This driver measures the champion against a
DIVERSIFIED opponent pool along two axes and records a per-cell win-rate
matrix with pooled Wilson 95% intervals, so a genuinely weak cell (CI upper
bound clearly below 0.5, or center << baseline) can be spotted and — if one
exists — one targeted counter-candidate can be screen→confirm'd against it.

Two axes (the champion always pilots its own `deck.csv` = stw champion):
- **tactics axis** — opponent piloting the SAME (mirror) deck but a different
  policy: greedy (the baseline anchor), 竹式 rule, take-tactics greedy, random.
- **deck axis** — a greedy opponent piloting a DIFFERENT archetype deck drawn
  from decks/candidates (dragapult, raging-bolt, a NAIC champion list, …),
  exercising the champion against boards it was not tuned on.

Each (cell, seed) shard is one `run_bench` call; shards for a cell pool into
one Wilson interval. Records are appended to a JSONL as they finish so a run
can be split across several invocations (mcts matches are ~13s each).

Usage (from the repo root):
    # screen the whole pool, one seed, N=20/cell, champion = FABLE_CONFIG
    python3 eval/opponent_pool.py run --cells all --n 20 --seeds 1940 \
        --champion-label baseline --out docs/opponent_pool/screen.jsonl

    # confirm a candidate on one weak cell (extra seeds, config delta)
    python3 eval/opponent_pool.py run --cells d_raging_bolt --n 20 \
        --seeds 2940,3940 --champion-label candidate \
        --champion-override '{"deviate_margin":0.05}' \
        --out docs/opponent_pool/confirm.jsonl

    # print the pooled matrix + weakest cells
    python3 eval/opponent_pool.py summary \
        docs/opponent_pool/screen.jsonl [more.jsonl ...]
"""
import argparse
import datetime
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)  # libcg.so & deck.csv resolve relative to the repo root

from eval.bench import run_bench  # noqa: E402
from main import FABLE_CONFIG  # noqa: E402

CANDIDATES = "decks/candidates"

# Ordered pool. deck=None means the opponent mirrors the champion deck.csv.
POOL = [
    # tactics axis — mirror deck, varied policy
    {"id": "t_greedy",    "axis": "tactics", "agent": "greedy",
     "deck": None, "note": "baseline anchor (SOT-1938 reference)"},
    {"id": "t_rule",      "axis": "tactics", "agent": "rule",
     "deck": None, "note": "竹式 rule policy"},
    {"id": "t_tactical",  "axis": "tactics", "agent": "tactical-greedy",
     "deck": None, "note": "take-tactics greedy"},
    {"id": "t_random",    "axis": "tactics", "agent": "random",
     "deck": None, "note": "floor sanity"},
    # deck axis — greedy opponent, different archetype
    {"id": "d_dragapult",     "axis": "deck", "agent": "greedy",
     "deck": f"{CANDIDATES}/01_dragapult.csv", "note": "dragapult"},
    {"id": "d_raging_bolt",   "axis": "deck", "agent": "greedy",
     "deck": f"{CANDIDATES}/02_raging_bolt_ogerpon.csv",
     "note": "raging bolt / ogerpon"},
    {"id": "d_lillie_champ",  "axis": "deck", "agent": "greedy",
     "deck": f"{CANDIDATES}/21_lillie_s_clefairy_ex_naic_champion.csv",
     "note": "lillie's clefairy ex (NAIC champion)"},
    {"id": "d_dragapult_naic", "axis": "deck", "agent": "greedy",
     "deck": f"{CANDIDATES}/22_dragapult_ex_naic_2nd.csv",
     "note": "dragapult ex (NAIC 2nd)"},
]
POOL_BY_ID = {c["id"]: c for c in POOL}


def wilson95(wins: int, n: int) -> list:
    if n == 0:
        return [None, None]
    z = 1.959963984540054
    p = wins / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [center - half, center + half]


def resolve_champion(override_json):
    config = dict(FABLE_CONFIG)
    if override_json:
        config.update(json.loads(override_json))
    return config


def run_cell(cell, seed, n, champion_config, champion_label):
    """One (cell, seed) shard: champion mcts (A) vs the cell's opponent (B)."""
    rep = run_bench("mcts", cell["agent"], n, seed, "deck.csv",
                    config_a=champion_config, deck_b_path=cell["deck"])
    faults = (rep["rejects"] + rep["exceptions"]
              + rep["fallbacks_a"] + rep["fallbacks_b"]
              + rep["budget_violations_a"] + rep["budget_violations_b"]
              + rep["planner_fallbacks_a"] + rep["planner_fallbacks_b"]
              + rep["degraded_a"] + rep["degraded_b"] + rep["unfinished"])
    return {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cell": cell["id"], "axis": cell["axis"],
        "opp_agent": cell["agent"], "opp_deck": cell["deck"] or "deck.csv",
        "champion_label": champion_label, "champion_config": champion_config,
        "seed": seed, "n": n,
        "wins_champ": rep["wins_a"], "wins_opp": rep["wins_b"],
        "draws": rep["draws"],
        "winrate_champ_excl_draws": rep["winrate_a_excl_draws"],
        "wilson95_excl_draws": rep["wilson95_excl_draws"],
        "faults_total": faults,
    }


def cmd_run(args):
    if args.cells == "all":
        cell_ids = [c["id"] for c in POOL]
    else:
        cell_ids = [c.strip() for c in args.cells.split(",") if c.strip()]
    for cid in cell_ids:
        if cid not in POOL_BY_ID:
            raise SystemExit(f"unknown cell {cid}; known={list(POOL_BY_ID)}")
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    if len(set(seeds)) != len(seeds):
        raise SystemExit(f"seeds must be distinct, got {seeds}")
    champion = resolve_champion(args.champion_override)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    print(f"OPPONENT-POOL run: champion={args.champion_label} "
          f"cells={cell_ids} seeds={seeds} n={args.n}\n"
          f"  config={champion}", flush=True)
    with open(args.out, "a") as f:
        for cid in cell_ids:
            cell = POOL_BY_ID[cid]
            for seed in seeds:
                print(f"-> cell {cid} ({cell['note']}) seed {seed} ...",
                      flush=True)
                rec = run_cell(cell, seed, args.n, champion,
                               args.champion_label)
                f.write(json.dumps(rec, sort_keys=True) + "\n")
                f.flush()
                lo, hi = rec["wilson95_excl_draws"]
                wr = rec["winrate_champ_excl_draws"]
                wr_s = f"{wr:.4f}" if wr is not None else "n/a"
                print(f"   champ {rec['wins_champ']}-{rec['wins_opp']} "
                      f"(draw {rec['draws']})  wr={wr_s} "
                      f"Wilson95=[{lo:.4f},{hi:.4f}] faults={rec['faults_total']}",
                      flush=True)
    print(f"appended to {args.out}")


def _pool_records(paths):
    recs = []
    for p in paths:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
    return recs


def cmd_summary(args):
    recs = _pool_records(args.paths)
    # group by (champion_label, cell)
    groups = {}
    for r in recs:
        key = (r["champion_label"], r["cell"])
        g = groups.setdefault(key, {"wins": 0, "opp": 0, "draws": 0,
                                    "faults": 0, "seeds": set(), "n": 0,
                                    "axis": r["axis"], "opp_agent": r["opp_agent"],
                                    "opp_deck": r["opp_deck"]})
        g["wins"] += r["wins_champ"]
        g["opp"] += r["wins_opp"]
        g["draws"] += r["draws"]
        g["faults"] += r["faults_total"]
        g["seeds"].add(r["seed"])
        g["n"] += r["n"]

    labels = sorted({k[0] for k in groups})
    print("\n=== OPPONENT-POOL matrix (champion win rate, draws excluded) ===")
    rows = []
    for (label, cell), g in groups.items():
        decided = g["wins"] + g["opp"]
        wr = g["wins"] / decided if decided else None
        lo, hi = wilson95(g["wins"], decided)
        rows.append({
            "label": label, "cell": cell, "axis": g["axis"],
            "opp_agent": g["opp_agent"], "opp_deck": g["opp_deck"],
            "N": g["n"], "seeds": len(g["seeds"]),
            "wins": g["wins"], "opp": g["opp"], "draws": g["draws"],
            "winrate": wr, "wilson_lo": lo, "wilson_hi": hi,
            "faults": g["faults"],
        })
    rows.sort(key=lambda r: (r["label"], r["axis"], r["cell"]))
    hdr = (f"{'label':<10} {'cell':<16} {'axis':<8} {'N':>4} "
           f"{'wr':>7} {'wilson95':>18} {'W-L-D':>10} {'flt':>4}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        wr_s = f"{r['winrate']:.3f}" if r["winrate"] is not None else "  n/a"
        ci = (f"[{r['wilson_lo']:.3f},{r['wilson_hi']:.3f}]"
              if r["wilson_lo"] is not None else "     n/a")
        wld = f"{r['wins']}-{r['opp']}-{r['draws']}"
        print(f"{r['label']:<10} {r['cell']:<16} {r['axis']:<8} {r['N']:>4} "
              f"{wr_s:>7} {ci:>18} {wld:>10} {r['faults']:>4}")

    # weakest cells for the baseline champion (lowest Wilson lower bound)
    base_rows = [r for r in rows if r["label"] == "baseline"
                 and r["wilson_lo"] is not None]
    if base_rows:
        print("\n=== weakest baseline cells (by Wilson lower bound) ===")
        for r in sorted(base_rows, key=lambda r: r["wilson_lo"])[:3]:
            flag = ""
            if r["wilson_hi"] < 0.5:
                flag = "  <-- LOSING (CI upper < 0.5)"
            elif r["winrate"] is not None and r["winrate"] < 0.5:
                flag = "  <-- sub-.500 center"
            print(f"  {r['cell']:<16} wr={r['winrate']:.3f} "
                  f"CI=[{r['wilson_lo']:.3f},{r['wilson_hi']:.3f}]{flag}")

    # promotion verdict when both baseline & candidate present for a cell
    cand_cells = {r["cell"] for r in rows if r["label"] == "candidate"}
    if cand_cells:
        print("\n=== promotion verdict (candidate vs baseline, per cell) ===")
        for cell in sorted(cand_cells):
            b = next((r for r in rows if r["label"] == "baseline"
                      and r["cell"] == cell), None)
            c = next((r for r in rows if r["label"] == "candidate"
                      and r["cell"] == cell), None)
            if not (b and c and b["winrate"] is not None
                    and c["wilson_lo"] is not None):
                continue
            promoted = c["wilson_lo"] > b["winrate"]
            print(f"  {cell}: baseline wr={b['winrate']:.3f} | candidate "
                  f"CI=[{c['wilson_lo']:.3f},{c['wilson_hi']:.3f}] -> "
                  f"{'PROMOTE' if promoted else 'NO-PROMOTE'} "
                  f"(gate: cand CI-lo {c['wilson_lo']:.3f} "
                  f"{'>' if promoted else '<='} base wr {b['winrate']:.3f})")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="measure champion vs pool cells")
    r.add_argument("--cells", default="all",
                   help="'all' or comma-separated cell ids")
    r.add_argument("--n", type=int, default=20, help="matches per (cell,seed)")
    r.add_argument("--seeds", required=True, help="comma-separated seeds")
    r.add_argument("--champion-label", default="baseline",
                   help="baseline | candidate (used by the promotion verdict)")
    r.add_argument("--champion-override", default=None,
                   help="JSON delta merged onto FABLE_CONFIG for the champion")
    r.add_argument("--out", default="docs/opponent_pool/pool.jsonl")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("summary", help="pool records and print the matrix")
    s.add_argument("paths", nargs="+", help="one or more pool JSONL files")
    s.set_defaults(func=cmd_summary)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
