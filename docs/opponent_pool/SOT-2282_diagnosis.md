# Field-representative oracle re-diagnosis (SOT-2282)

Parent: **SOT-2277** (Kaggle 順位向上サイクル第4次). Baseline champion: `main.FABLE_CONFIG`
(`mcts`, max_root_actions 6 / max_tree_depth 1 / n_worlds 4 / time_budget_s 0.8 / deviate_margin 0.1).
**Diagnosis only — champion behavior (`main.py`) is unchanged; no Kaggle submission.**

## Question

Through cycles 1–7 every algorithm lever was judged **local A/B saturated**, yet over the same period
the Kaggle public score *fell* (626.9 → 540 → 526; same-artifact re-score 540 → 505). Is that
"local saturation × Kaggle-rank decline" caused by an **oracle drift** — the local evaluation
opponents (greedy / rule / mirror deck) no longer representing the field — or is the saturation real?
This applies the biohub **SOT-2272** lesson (an apparent saturation whose true cause was on the
*measurement* side) to ptcg.

## Method — harden the SOT-1940 gauntlet to be field-representative

The SOT-1940 pool measured the champion only against **non-searching** pilots (greedy / rule /
tactical / random; its strongest cell was 竹式 `rule` at 0.60) on a largely dragapult-centric deck set.
The real Kaggle field runs agents that **search**, and the current (2026-08) meta has moved on. Two
additions make the gauntlet field-representative (`eval/opponent_pool.py`):

1. **A searching adversary.** New `opp_config` plumbing (`bench.run_bench(config_b=…)`) hands the
   opponent (agent B) the champion's own full-strength `FABLE_CONFIG` at the **real 0.8 s** budget, so
   the champion is measured against a genuine searching `mcts` adversary — mirror (`t_mcts`) and
   cross-deck (`dm_*`). This is the cell the SOT-1940 pool lacked.
2. **Current-meta archetypes.** The 2026-08 meta top decks — Marnie's Grimmsnarl ex (#1),
   Alakazam Dudunsparce (#2), Cynthia's Garchomp ex (#3), Raging Bolt Ogerpon (#4) — added on the
   deck axis. Grimmsnarl and Alakazam are faced by **both** a greedy (`dg_*`) and an mcts (`dm_*`)
   pilot on the *same* deck, so the policy-strength delta is directly measurable.

Champion pilots its own `deck.csv` throughout; side-alternating matches (fair). **N = 60 / cell**
(3 independent seeds `2282,4041,8080`) — every cell ≥ 40, exceeding the weak-cell expansion bar. Draws
excluded from the Wilson 95% interval. Records: `docs/opponent_pool/screen_sot2282.jsonl` (one row per
(cell, seed)). Analyzer: `eval/_sot2282_analyze.py`.

### Sibling-repo champions — SKIPPED (with reason)

Importing the `/workspaces/ptcg-agent-{matsu,take,ume,obo,gpt}` champions directly as opponents was
**not done**: those repos are engine forks with **divergent agent module trees** and their own
`cg.game` / `BaseAgent`, not import-compatible into claude's engine without a per-repo cross-engine
adapter (e.g. `take` exposes `archetype.py` / `profile.py` / `promoted_profile.json` and no `CONFIG`
in `main.py`; `matsu` exposes `CHAMPION_CONFIG = 6/1/4…`, structurally identical to claude's
`FABLE_CONFIG`). Because the sibling champions are the **same mcts/greedy family** differing mainly by
config / deck / eval-weights, the field-representative "strong searching adversary" is faithfully
captured by handing the opponent claude's own full-strength `mcts` @0.8 s (mirror + cross-deck). A
literal cross-repo agent bridge is substantial, fault-prone integration out of scope for a
no-behavior-change diagnostic; noted as a future lever if a later cycle needs the exact sibling
policies.

## Reproduce

```bash
# screen (searching-opponent + current-meta cells) — the committed record used seeds 2282,4041,8080
python3 eval/opponent_pool.py run --cells sot2282 --n 20 --seeds 2282,4041,8080 \
    --champion-label baseline --out docs/opponent_pool/screen_sot2282.jsonl
# SOT-1940-continuity cells (non-searching anchors), same seeds
python3 eval/opponent_pool.py run --cells sot1940 --n 20 --seeds 2282,4041,8080 \
    --champion-label baseline --out docs/opponent_pool/screen_sot2282.jsonl
# pooled per-cell Wilson95 + weak-cell flags + greedy↔mcts delta
python3 eval/_sot2282_analyze.py docs/opponent_pool/screen_sot2282.jsonl
```

`--cells sot2282` and `--cells sot1940` are named groups (see `CELL_GROUPS`); `--cells all` runs the
full 15-cell pool.

## Result (champion win rate, draws excluded; N = 60 / cell, faults = 0 everywhere)

| cell | axis | opponent | winrate | Wilson95 | W-L | flag |
| --- | --- | --- | --- | --- | --- | --- |
| t_greedy | tactics | greedy (mirror) | 0.550 | [0.425, 0.669] | 33-27 | |
| t_rule | tactics | 竹式 rule (mirror) | 0.600 | [0.474, 0.714] | 36-24 | |
| t_tactical | tactics | tactical-greedy (mirror) | 0.533 | [0.409, 0.654] | 32-28 | **WEAK (wr<0.55)** |
| t_random | tactics | random (mirror, floor) | 1.000 | [0.940, 1.000] | 60-0 | |
| **t_mcts** | tactics | **mcts @0.8s (mirror)** | **0.500** | [0.377, 0.623] | 30-30 | MIRROR (~0.50 expected) |
| d_dragapult | deck | greedy · dragapult | 0.917 | [0.819, 0.964] | 55-5 | |
| d_raging_bolt | deck | greedy · raging bolt | 0.733 | [0.610, 0.829] | 44-16 | |
| d_lillie_champ | deck | greedy · Lillie's Clefairy ex | 0.900 | [0.799, 0.953] | 54-6 | |
| d_dragapult_naic | deck | greedy · dragapult ex (NAIC 2nd) | 0.883 | [0.778, 0.942] | 53-7 | |
| dg_grimmsnarl | deck | greedy · Grimmsnarl (meta #1) | 0.833 | [0.720, 0.907] | 50-10 | |
| **dm_grimmsnarl** | deck | **mcts · Grimmsnarl (meta #1)** | 0.750 | [0.628, 0.842] | 45-15 | |
| dg_alakazam | deck | greedy · Alakazam (meta #2) | 0.967 | [0.886, 0.991] | 58-2 | |
| **dm_alakazam** | deck | **mcts · Alakazam (meta #2)** | 0.883 | [0.778, 0.942] | 53-7 | |
| **dm_garchomp** | deck | **mcts · Garchomp (meta #3)** | 0.767 | [0.646, 0.856] | 46-14 | |
| **dm_raging_bolt** | deck | **mcts · Raging Bolt (meta #4)** | 0.700 | [0.575, 0.801] | 42-18 | |

**Health:** faults (rejects / exceptions / fallbacks / budget-violations / degraded) = **0** across all
15 cells × 3 seeds.

**Policy-strength delta** (same meta deck, greedy → mcts opponent): Grimmsnarl −0.083, Alakazam −0.083.

### Reading

- **No confirmed losing cell.** No cell has a Wilson **upper** bound below 0.5 — not even against the
  searching `mcts` adversary on the current-meta decks the pool previously lacked. The only sub-0.55
  cell is `t_tactical` (0.533), whose interval [0.409, 0.654] **straddles parity** (upper 0.654 > 0.5):
  a marginal ~coin-flip on the mirror deck, not a loss.
- **Mirror sanity holds exactly.** `t_mcts` (champion vs its identical config + deck) = **0.500**
  (30-30) — the side-alternation is unbiased and ~0.50 is the symmetry baseline, confirming the
  searching-opponent harness is sound.
- **A stronger opponent does not expose a hidden weakness.** Handing the opponent real search on a meta
  deck costs the champion only ~8 points (greedy→mcts delta −0.083) and never flips a cell to losing;
  the deck axis stays uniformly strong (0.70–0.97) even against `mcts` pilots.
- **Higher fidelity, same shape as SOT-1940.** The softest cells remain the mirror-deck *policy*
  matchups (`t_tactical` 0.533, `t_mcts` 0.500, `t_greedy` 0.550); the deck axis is strong everywhere.
  Averaging 3 independent seeds also corrected single-seed noise — `t_tactical` read 0.80 at seed 2282
  alone but pools to 0.533 (cf. SOT-1940 / SOT-1938: the engine RNG is non-seedable, single-seed edges
  reverse).

## Conclusion — no oracle drift; the local saturation is real

**Oracle drift: NOT detected.** Even after making the gauntlet field-representative — a genuine
searching `mcts` adversary at real budget, plus the current-2026-08 meta decks the SOT-1940 pool
lacked — the champion has **no confirmed losing cell** and only one marginal ~parity cell
(`t_tactical`, mirror deck). The small greedy→mcts delta shows a stronger opponent surfaces no hidden
weakness. So the cycle 1–7 "local A/B saturation" is **real for the policy/algorithm axis**; it is
**not** an artifact of a too-weak local oracle — the opposite of biohub SOT-2272, where the weakness
lived in the measurement.

Therefore the Kaggle-rank decline (626 → 540 → 526) is **not** explained by a policy weakness the local
oracle failed to catch. It is consistent with (a) **relative scoring** — the field improving around a
static champion — and/or (b) a **deck-meta drift**: the pool's dragapult-centric candidates vs the
current Grimmsnarl / Alakazam / Garchomp / Raging-Bolt meta. That is the **deck axis**, owned by the
sibling issue **SOT-2284** (champion deck re-optimization to the 8月 meta), not the search/policy axis.
On the policy axis the recommendation is **MAINTAIN** the champion; the remaining lever is deck/meta.

Counter-implementation is out of scope here (diagnosis only). This change adds the reusable
searching-opponent + current-meta gauntlet and this record; `main.FABLE_CONFIG` is untouched.
