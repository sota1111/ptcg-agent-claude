"""ELO-consistent local evaluation harness (SOT-2334).

WHY THIS EXISTS
---------------
The Kaggle leaderboard for ``pokemon-tcg-ai-battle`` is an **ELO / rating**
ladder: every match moves both agents' rating (``analysis/kaggle_episodes.py``
reads each episode's ``initialScore`` -> ``updatedScore``). Beating a strong
opponent *raises* your rating; an **upset loss** to a *weak* opponent *drains*
it, and the drain is asymmetric — an ELO loss to someone you were expected to
beat costs far more points than the matching win would have earned.

Our local evaluation, by contrast, is **win-rate only** (``eval/bench.py`` +
``eval/opponent_pool.py`` report Wilson-CI win rates). Win rate is *orthogonal*
to ELO: an agent can sit at ~0.50 win rate against peers (looks "saturated" /
fine) while still **bleeding rating on the Kaggle ladder**, because its rare
losses land disproportionately against *weaker* opponents (upset losses) and
those are exactly the matches ELO punishes hardest.

This harness re-derives the champion's **converged ELO rating** and — crucially
— a **per-strength-tier decomposition of where the rating comes from and where
it leaks**, on the same local cabt engine used by the win-rate bench. It does
NOT replace the win-rate bench (that stays); it is the ELO-consistent *second*
signal the downstream defence/attack levers (SOT-2335 / SOT-2336) judge against.

WHAT IT MEASURES
----------------
A fixed **opponent field** spanning weak -> strong, each pinned to an *anchor
rating* (a strength prior; the champion's rating floats to balance the field):

    random  <  rule(竹式)  <  greedy  <  tactical-greedy
            <  mcts@low-budget  <  mcts@peer-budget  <  mcts@high-budget

The champion plays a deterministic round-robin against the field. We then:

1. Solve the champion's **fixed-point ELO rating** R* (the rating at which the
   net expected rating flow across all matches is zero — order-independent,
   the ELO analogue of a "performance rating"), using the standard logistic
   ELO expectation ``E = 1/(1 + 10**((R_opp - R_champ)/400))`` and K-factor.
2. Decompose the steady-state rating flow **per tier** at R*: win rate, the
   rating *gained from wins* and *drained by losses*, and the **net** — making
   visible that the peer tier is ~0.50 win rate & ~net-zero (looks saturated)
   while the **weak tiers net-negative** because their upset losses each cost
   ``K*E`` (E large) but their wins each earn only ``K*(1-E)`` (small).
3. Corroborate the *mechanism* by tagging every champion loss with the engine
   RESULT reason (same tagging as ``analysis/local_loss_tags.py``): board-wipe
   (盤面全滅) is expected to dominate the upset-loss drain (~93.8% baseline).

The ``summary`` command aggregates screen/confirm JSONL and prints the verdict:
whether the "peer win rate ~0.5 BUT weak-tier upset losses drain rating" gap is
reproduced, and (with >=3 independent seeds) whether it is *stable*.

DETERMINISM
-----------
Every match seed is derived from ``--seed`` via the repo ``Rng`` tree, so a
given ``--seed`` reproduces byte-for-byte. R* is solved by fixed-point epochs
over the recorded match set, so it is independent of match ordering.

Usage (from repo root):
    # screen: one seed, small N, whole field, reduced budgets for throughput
    python3 eval/elo_gauntlet.py run --n 12 --seeds 2334 \
        --champion-budget 0.12 --out docs/elo_gauntlet/screen.jsonl

    # confirm: >=3 independent seeds
    python3 eval/elo_gauntlet.py run --n 12 --seeds 12334,22334,32334 \
        --champion-budget 0.12 --out docs/elo_gauntlet/confirm.jsonl

    # verdict + per-tier rating decomposition
    python3 eval/elo_gauntlet.py summary docs/elo_gauntlet/*.jsonl
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)  # libcg.so & deck.csv resolve relative to the repo root

from cg import game  # noqa: E402
from agents import make_agent  # noqa: E402
from agents.rng import Rng  # noqa: E402
from main import FABLE_CONFIG  # noqa: E402

MAX_DECISIONS = 100000

# Engine RESULT.reason codes (cg/api.py LogType 23), mirroring
# analysis/local_loss_tags.py so the loss-cause tally is directly comparable.
REASON_TAG = {
    1: "prize_race_lost",   # opponent completed their prizes
    2: "deck_out",          # started a turn with an empty deck
    3: "board_wipe",        # no Pokemon left in the Active Spot (盤面全滅)
    4: "card_effect",       # a card effect ended the game
}

# --- Opponent field ---------------------------------------------------------
# anchor = fixed strength-prior rating (the champion's rating floats to balance
# the field). budget = mcts per-move search seconds (None for non-searching
# policies). The weak/mid tiers sit BELOW where the champion converges, so any
# loss to them is by definition an ELO "upset loss" (the case that drains
# rating). The peer tier is a same-budget mcts mirror -> ~0.50 win rate.
def build_field(champion_budget: float, include_elite: bool = True,
                elite_mult: float = 6.0):
    """The weak->strong anchored opponent field.

    ``include_elite`` (SOT-2336, the *attack* lever) appends a genuinely
    strong ``mcts_elite`` reference above the peer mirror — an external-class
    proxy (same search agent given ``elite_mult`` x the champion's per-move
    budget, so it explores far more deeply). Its anchor sits well above where
    the champion converges, so it is a *strong* (non-upset) tier: the place
    where beating the opponent EARNS the most rating (upset win, ``K*(1-E)``
    with E small). This is the cell the attack lever must convert. It is
    ADDITIVE — omitting it (``include_elite=False``) reproduces the exact
    SOT-2334 diagnostic field.
    """
    peer_budget = champion_budget
    near_budget = round(champion_budget / 2.0, 4)
    strong_budget = round(champion_budget * 2.5, 4)
    elite_budget = round(champion_budget * elite_mult, 4)
    mcts_cfg = dict(FABLE_CONFIG)

    def mcts_at(budget):
        return {**mcts_cfg, "time_budget_s": budget}

    field = [
        {"id": "random",    "tier": "weak", "agent": "random",
         "anchor": 1000.0, "opp_config": None,
         "note": "random legal (floor)"},
        {"id": "rule",      "tier": "weak", "agent": "rule",
         "anchor": 1230.0, "opp_config": None,
         "note": "竹式 rule policy"},
        {"id": "greedy",    "tier": "mid",  "agent": "greedy",
         "anchor": 1330.0, "opp_config": None,
         "note": "1-ply greedy (SOT-1938 baseline anchor)"},
        {"id": "tactical",  "tier": "mid",  "agent": "tactical-greedy",
         "anchor": 1380.0, "opp_config": None,
         "note": "take-tactics greedy"},
        {"id": "mcts_low",  "tier": "near_peer", "agent": "mcts",
         "anchor": 1470.0, "opp_config": mcts_at(near_budget),
         "note": f"mcts @{near_budget}s (weakened search)"},
        {"id": "mcts_peer", "tier": "peer", "agent": "mcts",
         "anchor": 1560.0, "opp_config": mcts_at(peer_budget),
         "note": f"mcts @{peer_budget}s (same-budget mirror)"},
        {"id": "mcts_high", "tier": "strong", "agent": "mcts",
         "anchor": 1660.0, "opp_config": mcts_at(strong_budget),
         "note": f"mcts @{strong_budget}s (stronger search)"},
    ]
    if include_elite:
        field.append(
            {"id": "mcts_elite", "tier": "elite", "agent": "mcts",
             "anchor": 1760.0, "opp_config": mcts_at(elite_budget),
             "note": f"mcts @{elite_budget}s ({elite_mult}x deep search, "
                     f"external-class reference)"})
    return field


# --- SOT-2336 attack lever: champion *decision-commitment* diff ---------------
# The champion's ``deviate_margin=0.1`` (main.py FABLE_CONFIG) is the SOT-1672
# conservatism band: MCTS must beat the 1-ply greedy-prior action by >0.1 on the
# evaluator's value scale before the champion will *leave* the prior action.
# HYPOTHESIS (attack): that band was tuned to suppress MCTS *noise* against the
# OLD field. Against a genuinely strong opponent the greedy prior's static read
# is itself more often wrong (strong search punishes shallow lines), so the band
# over-suppresses exactly the MCTS-discovered lines that would BEAT strong
# search — capping upset-win rating gain. Lowering the band trusts the deeper
# read more. This is a QUALITATIVE change to *which action the champion commits
# to*, orthogonal to the closed axes: value-net leaf eval (SOT-1837/2283,
# rejected) and belief width n_worlds (SOT-2172, rejected) and raw compute. The
# ELO-proxy R* is the judge: it nets the strong-tier acquisition against any new
# weak-tier upset-loss leak automatically.
ATTACK_LEVER = {"deviate_margin": 0.02}


TIER_ORDER = ["weak", "mid", "near_peer", "peer", "strong", "elite"]

DEFAULT_K = 32.0
DEFAULT_R0 = 1500.0


def _terminal_reason(obs: dict):
    for lg in obs.get("logs") or []:
        if lg.get("type") == 23:  # RESULT
            return lg.get("reason")
    return None


def load_deck(path: str) -> list:
    with open(path) as f:
        return [int(x) for x in f.read().split("\n")[:60]]


def play_match(agent0, agent1):
    """One engine match. Returns (result, reason, decisions, fault).

    result: 0/1 winner seat, 2 draw, -1 unfinished/fault.
    reason: engine RESULT.reason of the terminal obs (or None).
    """
    obs, start = game.battle_start(agent0._deck, agent1._deck)
    if obs is None:
        raise RuntimeError(
            f"battle_start failed: errorPlayer={start.errorPlayer} "
            f"errorType={start.errorType}")
    try:
        decisions = 0
        while decisions < MAX_DECISIONS:
            current = obs.get("current") or {}
            result = current.get("result", -1)
            if result != -1:
                return result, _terminal_reason(obs), decisions, False
            agent = agent0 if current.get("yourIndex", 0) == 0 else agent1
            try:
                action = agent.act(obs)
            except Exception:
                return -1, None, decisions, True   # agent exception
            try:
                obs = game.battle_select(action)
            except Exception:
                return -1, None, decisions, True   # engine reject
            decisions += 1
        return -1, None, decisions, True
    finally:
        game.battle_finish()


def elo_expected(r_champ: float, r_opp: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((r_opp - r_champ) / 400.0))


def run_cell(cell, champion_config, n, base_rng, champ_deck, champ_deck_path):
    """Play n side-alternating champion(mcts) vs cell-opponent matches."""
    opp_deck = (load_deck(cell["deck"]) if cell.get("deck") else champ_deck)
    rows = []
    faults = 0
    for i in range(n):
        seed_a = base_rng.child(f"{cell['id']}.match{i}.a").seed
        seed_b = base_rng.child(f"{cell['id']}.match{i}.b").seed
        champ = make_agent("mcts", seed=seed_a, deck=champ_deck,
                           **(champion_config or {}))
        opp = make_agent(cell["agent"], seed=seed_b, deck=opp_deck,
                         **(cell.get("opp_config") or {}))
        champ_first = (i % 2 == 0)
        p0, p1 = (champ, opp) if champ_first else (opp, champ)
        result, reason, _dec, fault = play_match(p0, p1)
        if fault or result == -1:
            faults += 1
            continue
        if result == 2:
            outcome, score = "draw", 0.5
            reason_tag = "draw"
        else:
            champ_won = (result == 0) == champ_first
            outcome = "win" if champ_won else "loss"
            score = 1.0 if champ_won else 0.0
            # tag the terminal RESULT reason on champion LOSSES (same
            # convention as analysis/local_loss_tags.py)
            reason_tag = (REASON_TAG.get(reason, "unknown")
                          if outcome == "loss" else "")
        rows.append({"match": i, "outcome": outcome, "score": score,
                     "reason_tag": reason_tag})
    return rows, faults


def _parse_eval_weights_override(raw):
    """Parse the --champion-eval-weights JSON object (or None)."""
    if not raw:
        return None
    try:
        override = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"--champion-eval-weights must be JSON: {e}")
    if not isinstance(override, dict):
        raise SystemExit("--champion-eval-weights must be a JSON object")
    return override


def cmd_run(args):
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    if len(set(seeds)) != len(seeds):
        raise SystemExit(f"seeds must be distinct, got {seeds}")
    # The opponent field (build_field) stays pinned to the BASELINE champion
    # (FABLE_CONFIG). The candidate overrides below change ONLY the champion
    # under test, so a defence/attack candidate (SOT-2335/2336) is measured
    # against the SAME fixed reference field the baseline champion was — an
    # isolated candidate-vs-field A/B rather than a moving mirror.
    field = build_field(args.champion_budget,
                        include_elite=not args.no_elite,
                        elite_mult=args.elite_mult)
    champion_config = {**dict(FABLE_CONFIG),
                       "time_budget_s": args.champion_budget}
    # SOT-2335 defence lever: --champion-eval-weights overrides ONLY the
    # champion-under-test's eval_weights.
    ew_override = _parse_eval_weights_override(
        getattr(args, "champion_eval_weights", None))
    if ew_override:
        champion_config["eval_weights"] = {
            **dict(FABLE_CONFIG.get("eval_weights") or {}), **ew_override}
    # SOT-2336 attack lever: --champion-overrides injects an arbitrary champion
    # diff (e.g. the lowered deviate_margin) WITHOUT touching main.py. Empty/
    # absent keeps the shipped champion byte-identical (the baseline arm).
    overrides = {}
    if args.champion_overrides:
        overrides = json.loads(args.champion_overrides)
        if not isinstance(overrides, dict):
            raise SystemExit("--champion-overrides must be a JSON object")
        champion_config.update(overrides)
    if args.attack_lever:
        overrides = {**overrides, **ATTACK_LEVER}
        champion_config.update(ATTACK_LEVER)
    champ_deck = load_deck(args.deck)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    print(f"ELO-GAUNTLET run: seeds={seeds} n={args.n} "
          f"champion_budget={args.champion_budget}s K={args.k} "
          f"overrides={overrides or '(baseline)'}\n"
          f"  field={[c['id'] for c in field]}\n"
          f"  champion_eval_weights_override={ew_override}", flush=True)
    with open(args.out, "a") as f:
        for seed in seeds:
            base = Rng(seed)
            for cell in field:
                print(f"-> seed {seed} cell {cell['id']} "
                      f"({cell['note']}) ...", flush=True)
                rows, faults = run_cell(cell, champion_config, args.n, base,
                                        champ_deck, args.deck)
                wins = sum(1 for r in rows if r["outcome"] == "win")
                losses = sum(1 for r in rows if r["outcome"] == "loss")
                draws = sum(1 for r in rows if r["outcome"] == "draw")
                loss_tags = {}
                for r in rows:
                    if r["outcome"] == "loss":
                        loss_tags[r["reason_tag"]] = loss_tags.get(
                            r["reason_tag"], 0) + 1
                rec = {
                    "ts": datetime.datetime.now(
                        datetime.timezone.utc).isoformat(),
                    "seed": seed, "cell": cell["id"], "tier": cell["tier"],
                    "opp_agent": cell["agent"], "anchor": cell["anchor"],
                    "opp_config": cell.get("opp_config") or {},
                    "champion_budget": args.champion_budget,
                    "champion_eval_weights_override": ew_override or {},
                    "champion_overrides": overrides,
                    "n": len(rows), "faults": faults,
                    "wins": wins, "losses": losses, "draws": draws,
                    "loss_by_tag": loss_tags,
                }
                f.write(json.dumps(rec, sort_keys=True) + "\n")
                f.flush()
                decided = wins + losses
                wr = wins / decided if decided else float("nan")
                print(f"   champ {wins}-{losses} (draw {draws}) wr={wr:.3f} "
                      f"loss_tags={loss_tags} faults={faults}", flush=True)
    print(f"appended to {args.out}")


# --- summary / verdict ------------------------------------------------------
def _read(paths):
    recs = []
    for p in paths:
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
    return recs


def _net_flow(cells, r, k):
    """Net expected rating flow at rating r (sum over cells of realised score
    minus ELO-expected score, scaled by K). Strictly DECREASING in r."""
    net = 0.0
    for c in cells:
        e = elo_expected(r, c["anchor"])
        score = c["wins"] * 1.0 + c["draws"] * 0.5
        n = c["wins"] + c["losses"] + c["draws"]
        net += k * (score - e * n)
    return net


def solve_rating(cells, k=DEFAULT_K, lo=600.0, hi=2600.0, tol=1e-6):
    """Fixed-point champion rating R* = the rating at which the net expected
    rating flow across the whole match set is zero (the ELO "performance
    rating"). Solved by bisection since net_flow is strictly decreasing in r;
    order-free (depends only on per-cell win/loss/draw counts). If the champion
    beats (or loses to) the entire field even at the bound, R* clamps to it.
    """
    if not any(c["wins"] + c["losses"] + c["draws"] for c in cells):
        return DEFAULT_R0
    if _net_flow(cells, hi, k) > 0:   # still winning-expectation at the ceiling
        return hi
    if _net_flow(cells, lo, k) < 0:   # already losing-expectation at the floor
        return lo
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _net_flow(cells, mid, k) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def _agg_by_cell(recs_for_seed):
    by_cell = {}
    for r in recs_for_seed:
        c = by_cell.setdefault(r["cell"], {
            "cell": r["cell"], "tier": r["tier"], "anchor": r["anchor"],
            "opp_agent": r["opp_agent"], "wins": 0, "losses": 0, "draws": 0,
            "loss_by_tag": {}})
        c["wins"] += r["wins"]
        c["losses"] += r["losses"]
        c["draws"] += r["draws"]
        for tag, v in (r.get("loss_by_tag") or {}).items():
            c["loss_by_tag"][tag] = c["loss_by_tag"].get(tag, 0) + v
    return list(by_cell.values())


def decompose(cells, r_star, k=DEFAULT_K):
    """Steady-state per-cell rating-flow decomposition at R*.

    For each cell: gain_from_wins = wins * k*(1-E); drain_from_losses =
    losses * k*(0-E); net = gain + drain (+ draw term). E at R*.
    """
    out = []
    for c in cells:
        e = elo_expected(r_star, c["anchor"])
        decided = c["wins"] + c["losses"]
        wr = c["wins"] / decided if decided else None
        gain = c["wins"] * k * (1.0 - e)
        drain = c["losses"] * k * (0.0 - e)
        draw_flow = c["draws"] * k * (0.5 - e)
        out.append({**c, "expected": e, "winrate": wr,
                    "gain_from_wins": gain, "drain_from_losses": drain,
                    "draw_flow": draw_flow, "net": gain + drain + draw_flow,
                    "is_upset_tier": c["anchor"] < r_star})
    return out


def cmd_summary(args):
    recs = _read(args.paths)
    if not recs:
        raise SystemExit("no records")
    k = args.k
    seeds = sorted({r["seed"] for r in recs})
    total_faults = sum(r.get("faults", 0) for r in recs)

    per_seed = {}
    for seed in seeds:
        cells = _agg_by_cell([r for r in recs if r["seed"] == seed])
        r_star = solve_rating(cells, k=k)
        dec = decompose(cells, r_star, k=k)
        per_seed[seed] = {"r_star": r_star, "cells": dec}

    print(f"\n=== ELO-GAUNTLET summary (K={k}, seeds={seeds}, "
          f"faults={total_faults}) ===")
    print("champion converged rating R* per seed: " +
          ", ".join(f"{s}:{per_seed[s]['r_star']:.1f}" for s in seeds))

    # pooled decomposition (sum matches across seeds, single R*)
    pooled_cells = _agg_by_cell(recs)
    r_star_pooled = solve_rating(pooled_cells, k=k)
    dec = decompose(pooled_cells, r_star_pooled, k=k)
    dec.sort(key=lambda d: d["anchor"])
    print(f"\n--- pooled per-cell decomposition (R*={r_star_pooled:.1f}) ---")
    hdr = (f"{'cell':<10} {'tier':<10} {'anchor':>7} {'N':>4} {'wr':>6} "
           f"{'E@R*':>6} {'+wins':>8} {'-losses':>8} {'net':>8} up")
    print(hdr)
    print("-" * len(hdr))
    for d in dec:
        decided = d["wins"] + d["losses"]
        wr_s = f"{d['winrate']:.3f}" if d["winrate"] is not None else "  n/a"
        print(f"{d['cell']:<10} {d['tier']:<10} {d['anchor']:>7.0f} "
              f"{decided:>4} {wr_s:>6} {d['expected']:>6.3f} "
              f"{d['gain_from_wins']:>+8.1f} {d['drain_from_losses']:>+8.1f} "
              f"{d['net']:>+8.1f} {'Y' if d['is_upset_tier'] else '.'}")

    # upset-loss drain vs peer neutrality
    upset = [d for d in dec if d["is_upset_tier"]]
    peer = [d for d in dec if d["tier"] == "peer"]
    upset_drain = sum(d["drain_from_losses"] for d in upset)
    upset_gain = sum(d["gain_from_wins"] for d in upset)
    upset_net = sum(d["net"] for d in upset)
    # upset敗北率: the fraction of decided upset-tier matches the champion
    # LOST — the primary metric the SOT-2335 defence lever must cut (a lower
    # upset-loss rate is fewer rating-draining upsets). Reported alongside NET.
    upset_losses = sum(d["losses"] for d in upset)
    upset_wins = sum(d["wins"] for d in upset)
    upset_decided = upset_wins + upset_losses
    upset_loss_rate = (upset_losses / upset_decided) if upset_decided else float("nan")
    peer_wr = (sum(p["wins"] for p in peer) /
               max(1, sum(p["wins"] + p["losses"] for p in peer)))
    peer_net = sum(p["net"] for p in peer)

    # board-wipe share among ALL champion losses
    all_loss_tags = {}
    total_losses = 0
    for d in dec:
        total_losses += d["losses"]
        for tag, v in d["loss_by_tag"].items():
            all_loss_tags[tag] = all_loss_tags.get(tag, 0) + v
    bw = all_loss_tags.get("board_wipe", 0)
    bw_pct = (100.0 * bw / total_losses) if total_losses else 0.0

    print(f"\n--- rating-flow attribution (at R*={r_star_pooled:.1f}) ---")
    print(f"  upset tiers (anchor<R*): +wins {upset_gain:+.1f}  "
          f"-losses {upset_drain:+.1f}  NET {upset_net:+.1f}")
    print(f"  upset敗北率 (upset-tier loss rate): {upset_loss_rate:.3f} "
          f"({upset_losses}/{upset_decided} decided)")
    print(f"  peer tier: winrate {peer_wr:.3f}  NET {peer_net:+.1f}")
    print(f"  champion losses: {total_losses}  board_wipe {bw} "
          f"({bw_pct:.1f}%)  all_tags={all_loss_tags}")

    # field-wide win rate = what the existing win-rate bench "sees".
    field_wins = sum(d["wins"] for d in dec)
    field_dec = field_wins + sum(d["losses"] for d in dec)
    field_wr = field_wins / field_dec if field_dec else float("nan")

    # --- verdict ---
    # The ELO/win-rate DIVERGENCE is reproduced when the win-rate reading says
    # the champion is HEALTHY (at-least parity vs the peer mirror, so the
    # win-rate bench sees no weak cell) YET the ELO decomposition shows the
    # upset tiers (opponents the champion is favoured over) NET-DRAIN rating,
    # because each upset loss costs K*E (E large) while each upset win earns
    # only K*(1-E). This is exactly the blind spot: win rate ~parity/above
    # (looks saturated) while ELO leaks. Board-wipe upset losses are the
    # mechanism (corroborated against local_loss_tags.py ~93.8%).
    peer_healthy = peer_wr >= 0.45          # win-rate bench sees no peer weakness
    upset_drains = upset_net < 0 and upset_drain < 0
    reproduced = peer_healthy and upset_drains
    stable = None
    if len(seeds) >= 3:
        # per-seed: upset tiers net-negative on each independent seed
        per_seed_upset_neg = []
        for seed in seeds:
            ds = per_seed[seed]["cells"]
            un = sum(d["net"] for d in ds if d["is_upset_tier"])
            per_seed_upset_neg.append(un < 0)
        stable = all(per_seed_upset_neg)
        print(f"\n  per-seed upset-tier NET<0: "
              f"{dict(zip(seeds, per_seed_upset_neg))}")

    print(f"\n=== VERDICT ===")
    print(f"  win-rate reading: field wr={field_wr:.3f}, peer mirror "
          f"wr={peer_wr:.3f} -> champion looks {'HEALTHY' if peer_healthy else 'WEAK'} "
          f"(no losing cell = 'saturated')")
    print(f"  ELO reading: upset tiers NET {upset_net:+.1f} "
          f"(drain {upset_drain:+.1f} from upset losses) -> "
          f"{'LEAKING rating' if upset_drains else 'not leaking'}")
    print(f"  board-wipe dominates losses: {bw_pct:.1f}%")
    if stable is not None:
        print(f"  stable across {len(seeds)} independent seeds: {stable}")
    verdict = ("REPRODUCED" if reproduced and (stable is None or stable)
               else "NOT-REPRODUCED")
    print(f"  ELO/win-rate divergence: {verdict}")
    return verdict


# --- SOT-2336 attack-lever A/B comparison -----------------------------------
# Acquisition tiers = where beating the opponent EARNS rating (peer & up). The
# attack lever must lift these WITHOUT regressing the upset (weak) tiers.
ACQUISITION_TIERS = ("peer", "strong", "elite")
# Tiers the champion is favoured over (upset-LOSS risk = rating leak). The
# regression guard is on their RAW win rate — R*-independent, unlike upset_net
# (which mechanically drops when a strong-tier gain lifts R*, since drain=K*E
# grows with R*). "No new upset losses" == defensive win rate not falling.
DEFENSIVE_TIERS = ("weak", "mid", "near_peer")
RSTAR_MARGIN = 5.0       # min pooled R* gain to call an improvement (ELO pts)
DEFENSE_WR_TOL = 0.03    # allowed defensive-tier win-rate slip before regression


def _tier_wr(cells, tiers):
    tiers = set(tiers)
    w = sum(c["wins"] for c in cells if c["tier"] in tiers)
    d = w + sum(c["losses"] for c in cells if c["tier"] in tiers)
    return (w / d) if d else None


def compute_compare(base_recs, variant_recs, k=DEFAULT_K):
    """Pure A/B judge for the attack lever (SOT-2336).

    Returns a dict with pooled/per-seed R* for both arms, acquisition-tier win
    rate, upset-tier NET (each at its own arm's R*), and a PROMOTE/NON-PROMOTE
    verdict. Promotion requires (1) pooled R* gain >= RSTAR_MARGIN, (2) R* gain
    on EVERY shared seed (confirm-stable), and (3) no defensive-tier win-rate
    regression beyond DEFENSE_WR_TOL (the lever must not buy strong-tier wins by
    leaking new weak-tier upset losses). Win-rate is orthogonal (SOT-2334) so R*
    is the primary acquisition signal; the defensive win rate is the guard.
    """
    def arm(recs):
        pooled = _agg_by_cell(recs)
        r_star = solve_rating(pooled, k=k)
        dec = decompose(pooled, r_star, k=k)
        upset_net = sum(d["net"] for d in dec if d["is_upset_tier"])
        seeds = sorted({r["seed"] for r in recs})
        per_seed = {}
        for s in seeds:
            pc = _agg_by_cell([r for r in recs if r["seed"] == s])
            per_seed[s] = solve_rating(pc, k=k)
        return {
            "r_star": r_star, "per_seed_r_star": per_seed,
            "upset_net": upset_net,
            "acq_wr": _tier_wr(pooled, ACQUISITION_TIERS),
            "elite_wr": _tier_wr(pooled, ("elite",)),
            "strong_wr": _tier_wr(pooled, ("strong",)),
            "defensive_wr": _tier_wr(pooled, DEFENSIVE_TIERS),
            "cells": dec, "seeds": seeds,
        }

    base = arm(base_recs)
    var = arm(variant_recs)
    r_star_gain = var["r_star"] - base["r_star"]
    shared = [s for s in var["per_seed_r_star"] if s in base["per_seed_r_star"]]
    per_seed_gain = {s: var["per_seed_r_star"][s] - base["per_seed_r_star"][s]
                     for s in shared}
    all_seeds_up = bool(shared) and all(g > 0 for g in per_seed_gain.values())
    def_delta = ((var["defensive_wr"] or 0.0) - (base["defensive_wr"] or 0.0))
    no_regression = def_delta >= -DEFENSE_WR_TOL
    promote = (r_star_gain >= RSTAR_MARGIN and all_seeds_up and no_regression)
    return {
        "base": base, "variant": var,
        "r_star_gain": r_star_gain, "per_seed_gain": per_seed_gain,
        "all_seeds_up": all_seeds_up,
        "defensive_wr_delta": def_delta, "upset_delta": var["upset_net"] - base["upset_net"],
        "no_regression": no_regression,
        "verdict": "PROMOTE" if promote else "NON-PROMOTE",
    }


def cmd_compare(args):
    base_recs = _read([args.base])
    var_recs = _read([args.variant])
    if not base_recs or not var_recs:
        raise SystemExit("both --base and --variant must have records")
    res = compute_compare(base_recs, var_recs, k=args.k)
    b, v = res["base"], res["variant"]
    print(f"\n=== ATTACK-LEVER A/B (SOT-2336, K={args.k}) ===")
    print(f"  base    R*={b['r_star']:.1f}  acq_wr={_fmt(b['acq_wr'])}  "
          f"strong_wr={_fmt(b['strong_wr'])}  elite_wr={_fmt(b['elite_wr'])}  "
          f"def_wr={_fmt(b['defensive_wr'])}")
    print(f"  variant R*={v['r_star']:.1f}  acq_wr={_fmt(v['acq_wr'])}  "
          f"strong_wr={_fmt(v['strong_wr'])}  elite_wr={_fmt(v['elite_wr'])}  "
          f"def_wr={_fmt(v['defensive_wr'])}")
    print(f"  R* gain: {res['r_star_gain']:+.1f} "
          f"(need >= {RSTAR_MARGIN:+.1f})")
    print(f"  per-seed R* gain: "
          f"{ {s: round(g, 1) for s, g in res['per_seed_gain'].items()} } "
          f"-> all seeds up: {res['all_seeds_up']}")
    print(f"  defensive-tier wr delta: {res['defensive_wr_delta']:+.3f} "
          f"(regression if < {-DEFENSE_WR_TOL:+.3f}) -> "
          f"no_regression: {res['no_regression']}")
    print(f"\n  VERDICT: {res['verdict']}")
    return res


def _fmt(x):
    return f"{x:.3f}" if x is not None else " n/a"


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="play the champion vs the ELO field")
    r.add_argument("--n", type=int, default=12,
                   help="matches per (cell,seed)")
    r.add_argument("--seeds", required=True, help="comma-separated seeds")
    r.add_argument("--champion-budget", type=float, default=0.12,
                   help="champion (and peer mirror) mcts per-move seconds; "
                        "reduced from the shipped 0.8s for throughput")
    r.add_argument("--k", type=float, default=DEFAULT_K,
                   help="ELO K-factor (recorded; used by summary)")
    r.add_argument("--champion-eval-weights", default=None,
                   help="JSON object merged into the champion-under-test's "
                        "eval_weights ONLY (the opponent field stays baseline "
                        "FABLE_CONFIG); e.g. '{\"bench_dev\":0.5,"
                        "\"bench_dev_cap\":2}'. Isolates a defence/attack "
                        "candidate against the fixed reference field.")
    r.add_argument("--deck", default="deck.csv")
    r.add_argument("--out", default="docs/elo_gauntlet/pool.jsonl")
    r.add_argument("--no-elite", action="store_true",
                   help="omit the SOT-2336 mcts_elite strong cell "
                        "(reproduces the SOT-2334 diagnostic field)")
    r.add_argument("--elite-mult", type=float, default=6.0,
                   help="mcts_elite per-move budget as a multiple of the "
                        "champion budget (SOT-2336 external-class reference)")
    r.add_argument("--champion-overrides", default="",
                   help="JSON object merged onto the champion config for an "
                        "A/B arm, e.g. '{\"deviate_margin\": 0.02}'")
    r.add_argument("--attack-lever", action="store_true",
                   help="apply the SOT-2336 ATTACK_LEVER champion diff "
                        "(shorthand for the recorded --champion-overrides)")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("summary", help="verdict + per-tier decomposition")
    s.add_argument("paths", nargs="+", help="one or more gauntlet JSONL files")
    s.add_argument("--k", type=float, default=DEFAULT_K)
    s.set_defaults(func=cmd_summary)

    c = sub.add_parser("compare", help="attack-lever A/B verdict (SOT-2336)")
    c.add_argument("--base", required=True, help="baseline-arm JSONL")
    c.add_argument("--variant", required=True, help="lever-arm JSONL")
    c.add_argument("--k", type=float, default=DEFAULT_K)
    c.set_defaults(func=cmd_compare)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
