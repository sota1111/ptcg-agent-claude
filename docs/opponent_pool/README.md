# Opponent-pool robustness screen (SOT-1940)

Parent: SOT-1936 (Kaggle 順位向上サイクル第1次) · baseline: SOT-1938.

## Question

Is the claude/fable champion (`mcts` under `main.FABLE_CONFIG`) **overfit** to the single
reference opponent (greedy on the mirror deck) that the SOT-1938 baseline measured? Measure the
champion against a **diversified opponent pool** along two axes, record a per-cell win-rate matrix
with pooled Wilson 95% intervals, and — if a cell is clearly weak — screen→confirm **one** targeted
counter-candidate against it.

## Method

- Driver: `eval/opponent_pool.py` (`run` / `summary`). Each `(cell, seed)` shard is one
  `eval/bench.py::run_bench` call; shards for a cell pool into one Wilson interval. The champion
  always pilots its own `deck.csv`; `bench.py` gained a `--deck-b` / `deck_b_path` option so agent B
  can pilot a **different** archetype (SOT-1940).
- Two axes:
  - **tactics** — opponent on the *same* (mirror) deck, different policy: greedy (the baseline
    anchor), 竹式 `rule`, take-tactics `tactical-greedy`, `random`.
  - **deck** — a `greedy` opponent piloting a *different* archetype from `decks/candidates`
    (dragapult, raging-bolt/ogerpon, Lillie's Clefairy ex NAIC champion, dragapult ex NAIC 2nd).
- Screen: N=20 / cell, seed 1940. Records: `screen.jsonl`.
- Confirm: candidate on the weakest cell with an independent extra seed. Records: `confirm.jsonl`.

Reproduce:

```bash
python3 eval/opponent_pool.py run --cells all --n 20 --seeds 1940 \
    --champion-label baseline --out docs/opponent_pool/screen.jsonl
python3 eval/opponent_pool.py summary docs/opponent_pool/screen.jsonl docs/opponent_pool/confirm.jsonl
```

## Screen result (champion win rate, draws excluded)

| cell | axis | opponent | N | winrate | Wilson95 | W-L |
| --- | --- | --- | --- | --- | --- | --- |
| d_dragapult | deck | greedy · dragapult | 20 | 0.800 | [0.584, 0.919] | 16-4 |
| d_dragapult_naic | deck | greedy · dragapult ex (NAIC 2nd) | 20 | 0.850 | [0.640, 0.948] | 17-3 |
| d_lillie_champ | deck | greedy · Lillie's Clefairy ex (NAIC champ) | 20 | 0.700 | [0.481, 0.855] | 14-6 |
| d_raging_bolt | deck | greedy · raging bolt / ogerpon | 20 | 0.750 | [0.531, 0.888] | 15-5 |
| t_greedy | tactics | greedy (mirror, baseline anchor) | 20 | 0.550 | [0.342, 0.742] | 11-9 |
| t_random | tactics | random (mirror, floor) | 20 | 0.900 | [0.699, 0.972] | 18-2 |
| t_rule | tactics | 竹式 rule (mirror) | 20 → 40 | 0.60 (N=40) | [0.446, 0.737] | 24-16 |
| t_tactical | tactics | take-tactics greedy (mirror) | 20 | 0.600 | [0.387, 0.781] | 12-8 |

fault total across all cells/seeds: **0**.

### Reading

- **Deck axis is uniformly strong (0.70–0.85).** The champion is **not** overfit to a single
  archetype — it beats every foreign deck the greedy pilot brings, including two NAIC-caliber lists.
- **Tactics axis** is the soft side, as expected: the mirror-deck `greedy` anchor reproduces the
  SOT-1938 baseline (0.55 here ≈ 0.5625 there), and the strongest mirror policy, 竹式 `rule`, is the
  closest matchup.
- **No cell is losing.** No cell has a Wilson *upper* bound below 0.5; `t_random` (0.90) is a clean
  floor-sanity pass.

## Confirm — one candidate on the weakest cell (`t_rule`)

The screen's weakest single-seed cell was `t_rule` (10-10 = 0.50 at seed 1940). Candidate: **`n_worlds`
4 → 8** (more determinization worlds — the standard hidden-information robustness lever), applied as a
config override on `t_rule` only; the champion `deck.csv` and all other knobs unchanged.

| seed | baseline (n_worlds=4) | candidate (n_worlds=8) |
| --- | --- | --- |
| 1940 | 10-10 = 0.50 | 14-6 = 0.70 |
| 2940 | 14-6 = 0.70 | 11-9 = 0.55 |
| **pooled N=40** | **24-16 = 0.600** | **25-15 = 0.625, CI [0.470, 0.758]** |

**Verdict: NO-PROMOTE.** Gate = candidate CI-lower > baseline winrate → `0.470 ≤ 0.600`. The apparent
seed-1940 edge (0.70 vs 0.50) **completely reversed** at seed 2940 (0.55 vs 0.70): it was engine-RNG
variance (the engine RNG is non-seedable; cf. SOT-1938, SOT-1796 "confirm 単発最上位でも CI 重複なら追
検証必須"), not a real improvement. Pooling `t_rule` to N=40 also lifted the *baseline* itself to 0.60,
so it is no longer even the weakest cell.

## Conclusion

1. **Champion is robust across the diversified pool** — no losing cell; deck axis 0.70–0.85; softest
   matchup (mirror 竹式 rule) is 0.60 at N=40. Not overfit to the baseline reference opponent.
2. **Candidate `n_worlds=8` non-promoted** (Wilson CI). Per the non-promotion rule, **behavior is
   reverted**: the candidate was a CLI config override only — `main.FABLE_CONFIG` is unchanged and no
   champion behavior ships. This PR adds only the reusable eval driver + this record.
3. This reinforces the SOT-1936 family's saturation finding: the mcts champion's edge over strong
   mirror policies is marginal and search-quantity knobs (here `n_worlds`) do not convert it.
