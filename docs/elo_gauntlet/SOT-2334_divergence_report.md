# SOT-2334 — ELO / win-rate divergence diagnostic (cycle-1 foundation child)

Parent: **SOT-2332** (Kaggle順位向上サイクル 第1次).
This child is a **diagnostic / measurement foundation** — it introduces an
ELO-consistent local evaluation signal and reproduces the gap between what our
win-rate bench sees and what the Kaggle rating ladder actually rewards. It does
**not** change the champion and does **not** submit to Kaggle.

## Problem

- **Kaggle LB is an ELO / rating ladder.** `analysis/kaggle_episodes.py` reads
  each episode's `initialScore → updatedScore`: beating a strong opponent raises
  your rating, and an **upset loss** to a *weaker* opponent drains it. The ELO
  update is asymmetric — a loss to someone you were favoured to beat costs
  `K·E` points (E large) while the matching win earns only `K·(1−E)` (small).
- **Local eval is win-rate only.** `eval/bench.py` / `eval/kpi.py` report Wilson
  win rates. Win rate is **orthogonal** to ELO: an agent can sit at ~0.5 win
  rate vs peers (looks "saturated" / healthy) while still **bleeding rating**,
  because its rare losses land disproportionately on *weaker* opponents.

This is the suspected reason local A/B looked saturated (SOT-2277 cycle) while
the Kaggle rank slid (726→…): the two signals are measuring different things.

## Harness — `eval/elo_gauntlet.py`

A fixed **opponent field** spanning weak→strong, each pinned to an *anchor
rating* (a strength prior; the champion's rating floats to balance the field):

| cell | tier | anchor | opponent |
| --- | --- | --- | --- |
| random | weak | 1000 | random legal (floor) |
| rule | weak | 1230 | 竹式 rule policy |
| greedy | mid | 1330 | 1-ply greedy (SOT-1938 anchor) |
| tactical | mid | 1380 | take-tactics greedy |
| mcts_low | near_peer | 1470 | mcts @ ½ champion budget |
| mcts_peer | peer | 1560 | mcts @ champion budget (mirror) |
| mcts_high | strong | 1660 | mcts @ 2.5× champion budget |

The champion plays deterministic side-alternating matches against every cell,
then the harness:

1. **Solves the champion's fixed-point rating R\*** — the "performance rating"
   at which the net expected ELO flow across the whole match set is zero
   (bisection over a strictly-decreasing net-flow; **order-free**, depends only
   on per-cell W/L/D counts). This is the ELO analogue the win-rate bench lacks.
2. **Decomposes rating flow per tier at R\***: `gain_from_wins = wins·K·(1−E)`,
   `drain_from_losses = losses·K·(0−E)`, `net`. Cells whose anchor < R\* are
   *upset tiers* (the champion is favoured; any loss there is an upset loss).
3. **Tags every champion loss** with the engine `RESULT.reason` (same mapping as
   `analysis/local_loss_tags.py`) so the board-wipe (盤面全滅) share is directly
   comparable to the 93.8% baseline.

Determinism: every match seed derives from `--seed` via the repo `Rng` tree, so
a given seed reproduces byte-for-byte. R\* is order-free. The win-rate bench is
untouched and coexists.

Run:

```bash
# screen (1 seed, whole field)
python3 eval/elo_gauntlet.py run --n 20 --seeds 2334 --champion-budget 0.3 \
    --out docs/elo_gauntlet/screen.jsonl
# confirm (>=3 independent seeds)
python3 eval/elo_gauntlet.py run --n 20 --seeds 12334,22334,32334 \
    --champion-budget 0.3 --out docs/elo_gauntlet/confirm.jsonl
# verdict + per-tier decomposition
python3 eval/elo_gauntlet.py summary docs/elo_gauntlet/screen.jsonl \
    docs/elo_gauntlet/confirm.jsonl
```

## Result — screen (seed 2334, n=20/cell, champion_budget 0.3s, K=32)

Champion converged rating **R\* = 1539.5**.

| cell | tier | anchor | N | wr | E@R* | +wins | −losses | net | upset |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| random | weak | 1000 | 20 | 0.900 | 0.957 | +24.7 | −61.3 | −36.6 | Y |
| rule | weak | 1230 | 20 | 0.600 | 0.856 | +55.3 | −219.1 | **−163.8** | Y |
| greedy | mid | 1330 | 20 | 0.750 | 0.770 | +110.6 | −123.1 | −12.6 | Y |
| tactical | mid | 1380 | 20 | 0.650 | 0.715 | +118.7 | −160.1 | −41.4 | Y |
| mcts_low | near_peer | 1470 | 20 | 0.500 | 0.599 | +128.4 | −191.6 | −63.2 | Y |
| mcts_peer | **peer** | 1560 | 20 | **0.700** | 0.471 | +237.2 | −90.4 | +146.8 | . |
| mcts_high | strong | 1660 | 20 | 0.600 | 0.333 | +256.0 | −85.3 | +170.7 | . |

- **Win-rate reading:** field wr 0.671, **peer mirror wr 0.700** → no losing
  cell → the win-rate bench sees the champion as HEALTHY / "saturated".
- **ELO reading:** upset tiers (anchor<R\*) NET **−317.5** (drain **−755.2** from
  upset losses vs only +437.7 earned) → the champion is **LEAKING rating**.
- **Mechanism:** 46 champion losses, **board_wipe 44 = 95.7 %** (≈ the 93.8 %
  `analysis/local_loss_tags.py` baseline) → upset losses are overwhelmingly
  盤面全滅. The single worst leak is the `rule` (竹式) weak tier: **−163.8**.

**Screen verdict: ELO/win-rate divergence REPRODUCED.**

## Result — confirm (independent seeds 12334 / 22334 / 32334, n=20/cell, budget 0.3s, K=32)

Champion converged rating **R\* per seed = 1485.8 / 1479.3 / 1479.3** (pooled
**R\* = 1481.5**) — tight across independent seeds, so the rating estimate is not
a single-seed accident.

Pooled per-cell decomposition (N=60/cell across the 3 seeds):

| cell | tier | anchor | N | wr | E@R* | +wins | −losses | net | upset |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| random | weak | 1000 | 60 | 0.967 | 0.941 | +109.3 | −60.2 | +49.1 | Y |
| rule | weak | 1230 | 60 | 0.617 | 0.810 | +225.4 | −595.9 | **−370.4** | Y |
| greedy | mid | 1330 | 60 | 0.467 | 0.705 | +264.2 | −722.0 | **−457.8** | Y |
| tactical | mid | 1380 | 60 | 0.617 | 0.642 | +423.9 | −472.5 | −48.6 | Y |
| mcts_low | near_peer | 1470 | 60 | 0.450 | 0.516 | +417.8 | −545.4 | −127.6 | Y |
| mcts_peer | **peer** | 1560 | 60 | **0.583** | 0.389 | +684.5 | −311.1 | +373.4 | . |
| mcts_high | strong | 1660 | 60 | 0.567 | 0.264 | +801.3 | −219.2 | +582.1 | . |

- **Win-rate reading:** field wr 0.610, **peer mirror wr 0.583** → no losing cell
  → win-rate bench sees the champion as HEALTHY / "saturated".
- **ELO reading:** upset tiers (anchor<R\*) NET **−955.5** (drain **−2396.1** from
  upset losses vs only +1440.6 earned) → the champion is **LEAKING rating**.
- **Stability:** per-seed upset-tier NET<0 = `{12334: True, 22334: True,
  32334: True}` → **stable across all 3 independent seeds** (not a seed accident).
- **Mechanism:** 164 champion losses, **board_wipe 151 = 92.1 %** (≈ the 93.8 %
  `analysis/local_loss_tags.py` baseline) → upset losses are overwhelmingly
  盤面全滅. The worst leaks are the `rule` (竹式, −370.4) and `greedy` (−457.8)
  weak/mid tiers the champion is favoured over.

**Confirm verdict: ELO/win-rate divergence REPRODUCED and STABLE across ≥3
independent seeds.** (Verbatim: `python3 eval/elo_gauntlet.py summary
docs/elo_gauntlet/confirm.jsonl` → `stable across 3 independent seeds: True;
ELO/win-rate divergence: REPRODUCED`.)

## Interpretation / signal for downstream children

The divergence is real and mechanistic, not a measurement artifact:

- The **peer mirror is ~0.5–0.7 win rate** (looks fine to `eval/bench.py`), yet
  the champion **net-drains rating** because its losses concentrate on *weaker*
  opponents where each loss costs `K·E` with E≈0.72–0.96.
- **Board-wipe upset losses are the dominant drain** (~94–96 %). Cutting these
  weak-tier 盤面全滅 losses is worth far more ELO than any additional peer win.

This gives the downstream levers a rating-consistent target, not a win-rate one:

- **SOT-2335 (守備 / defence):** reduce weak-tier board-wipe upset losses (the
  `rule`/`random`/mid tiers). This harness's per-tier `net` and `board_wipe`
  share are the judgement signal — a defence lever must lift upset-tier NET
  (shrink `drain_from_losses`), not just field win rate.
- **SOT-2336 (攻撃 / attack):** any attacking change must be judged on ELO net,
  not win rate — a peer-facing win-rate gain that trades away weak-tier
  robustness can *lower* R\*.

**Promotion decision:** adopted as a **diagnostic signal** (not a champion
change). The champion, `main.py` submit path, and the win-rate bench are
unchanged; `eval/elo_gauntlet.py` is additive and exec-independent.

## Reproduce

`python3 -m unittest tests.test_elo_gauntlet` (8 tests: ELO expectation
monotonicity, order-free fixed-point rating, upset-loss asymmetry, peer-parity
but weak-tier-net-negative). Evidence JSONL: `docs/elo_gauntlet/screen.jsonl`,
`docs/elo_gauntlet/confirm.jsonl`.
