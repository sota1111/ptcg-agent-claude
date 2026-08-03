# SOT-2367 — Conditional survival-bench lever (non-promotion)

Cycle 2, child 3 of SOT-2363 (search/action-side board-wipe defence). Motivated
by the public Kaggle notebook
[keidroid/ptcg-ai-battle-rating-and-matchmaking-analysis](https://www.kaggle.com/code/keidroid/ptcg-ai-battle-rating-and-matchmaking-analysis).

## Notebook insight → lever hypothesis

The notebook shows that on this ladder the **first few matches dominate the final
rating**: two identical submissions diverged to a 200-point gap after one match,
369 after six, and the higher-rated one then drew ~3.5× the public match volume
(rating compounds — a good/bad start lands you in a band that self-reinforces).
The operational corollary: the highest-leverage improvement is cutting the
champion's worst loss mode, not its marginal win rate. SOT-2334/2365 localized
that mode to **upset-tier board_wipe** (~92% of losses), sub-classified into
`doomed_active_overcommit` and `unpromotable` (Active KO'd with an EMPTY bench →
no promote → instant wipe).

**Lever (SOT-2367):** a conditional survival-bench boost to the greedy action
prior — raise the play-priority of a basic Pokémon to the bench, but ONLY when a
wipe is imminent (`bench < survival_bench_floor` AND the Active is near-KO,
`hp/max_hp <= survival_hp_frac`, or absent). Distinct from the rejected
UNCONDITIONAL SOT-1941 `early_bench` (which paid tempo every turn): the insurance
basic is bought precisely when it prevents the `unpromotable` wipe.
Champion-default OFF (all three knobs 0 ⇒ `main.py` byte-identical).

## A/B result — NON-PROMOTION (robust across 3 parameterizations)

ELO-proxy gauntlet (`eval/elo_gauntlet.py`), paired seeds `2367,12367`,
n=16/cell, champion budget 0.12s, full field incl. elite. Baseline = shipped
champion (lever OFF).

| Config (boost/floor/frac) | R* | upset_tier_board_wipe_net | unpromotable | upset loss-rate |
| --- | ---: | ---: | ---: | ---: |
| **baseline (OFF)** | **1541.7** | −1276.9 | **21** | 0.344 |
| 30 / 1 / 0.5 | 1526.6 (−15.1) | −1154.1 | 24 (+3) | 0.338 |
| 10 / 1 / 0.4 | 1522.8 (−18.9) | −1258.9 | 22 (+1) | 0.362 |
| 15 / 2 / 0.6 | 1526.6 (−15.1) | −1268.1 | 24 (+3) | 0.350 |

- **Every** candidate config regressed the primary ELO metric R* by 15–19 pts.
  The promotion gate (R* non-inferior) fails on all three.
- **None** reduced the targeted `unpromotable` cause — all held or increased it
  (21 → 22/24/24). The lever does not fix the empty-bench wipe.
- The apparent `upset_tier_board_wipe_net` improvement in config 30/1/0.5
  (−1276.9 → −1154.1) is an R*-deflation artifact: `board_wipe_drain =
  losses × K·E(R*)`, and a lower R* mechanically shrinks E — the raw upset
  board_wipe losses (54 → 50) are within seed noise while unpromotable rose.
- Mechanism: forcing a bench play when the Active is already near-KO delays the
  wipe by exactly one Pokémon (the newly-benched basic is promoted, then KO'd
  with an empty bench again) while paying the tempo of not attacking — so the
  wipe still lands and the rating race is lost, costing R*.

**Conclusion:** the board_wipe rating leak is NOT addressable by biasing WHEN the
agent plays a bench basic. This reconfirms SOT-1941 (unconditional bench_boost,
rejected) and SOT-2335 (board-wipe-insurance eval terms, rejected) in the
conditional action-prior form. Champion maintained; the lever ships opt-in
(default OFF) as a closed, evidenced axis. Next rung stays SOT-2366 (preventive
retreat off the doomed Active — targets `doomed_active_overcommit`, the larger
cause) or external-knowledge import.

## Provenance

- Code: `agents/greedy_agent.py` (`_survival_bench_boost_value` /
  `_active_at_wipe_risk`), `agents/planner.py` (`PlannerConfig.survival_bench*`).
  `main.py` byte-identical (git diff --exit-code); champion behaviour unchanged.
- Tests: `tests/test_survival_bench.py` (9 new); full suite 177 green.
- Gauntlet JSONL: `docs/elo_gauntlet/sot2367_screen_{base,cand,candB,candC}.jsonl`.
