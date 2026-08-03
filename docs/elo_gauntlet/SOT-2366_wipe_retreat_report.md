# SOT-2366 — wipe-risk conservative retreat / anti-overcommit (cycle-2 action child)

Parent: **SOT-2363** (Kaggle順位向上サイクル 第2次). Dependency: **SOT-2365**
(board_wipe decision-cause attribution). Sibling: **SOT-2367** (survival bench,
rejected).

**Verdict: NON-PROMOTION.** The champion is unchanged (`main.py` byte-identical);
the lever ships **opt-in, default OFF** as a closed evidenced axis. No Kaggle
submission (parent SOT-2363 owns submission).

## Goal

cycle-1 localized the rating leak to upset-tier `board_wipe` (~92%) and SOT-2365
split those losses into decision causes. The larger cause is
**`doomed_active_overcommit`** (champion keeps sinking energy / evolution / attach
into an Active that is already doomed instead of retreating to preserve the
board). This child adds a **search/action lever** that, when a wipe is imminent,
(a) raises the retreat option priority and (b) lowers the priority of
resource-injection options targeting the doomed Active — targeting
`upset_tier_board_wipe_net` via the `doomed_active_overcommit` cause.

## What was added (additive, opt-in — champion byte-identical)

- **`agents/greedy_agent.GreedyAgent`** wipe-risk lever: `_active_doomed()` (Active
  near-KO — current HP ≤ `active_vulnerable_hp_frac`·max — **AND** the opponent's
  Active can KO it next turn, estimated best-attack damage with weakness /
  resistance), `_wipe_retreat_bonus()` (adds `wipe_retreat_bias` to the RETREAT
  score, only when a *survivable* bench target exists), `_wipe_overcommit_value()`
  (subtracts `wipe_overcommit_penalty` from attach-to-active / evolve-of-active).
- **`agents/planner.PlannerConfig`** knobs `wipe_retreat_bias` /
  `wipe_overcommit_penalty` / `active_vulnerable_hp_frac` (default `0/0/0` ⇒
  `_score_option` byte-identical; `main.py` FABLE_CONFIG never sets them), threaded
  into the shared GreedyAgent that serves the root prior and rollout policy.
- **15 unit tests** (`tests/test_wipe_retreat.py`); full suite 192 green.

## Lever rationale (new evidence, not a closed-axis re-try)

- Distinct from **SOT-1863 / SOT-2335** (board-wipe *eval bonus*, rejected): this
  changes **action selection**, not leaf value.
- Distinct from **SOT-1941** (unconditional greedy `bench_boost`, rejected) and
  **SOT-2367** (conditional survival-*bench* play, rejected): the lever is
  **retreat / anti-overcommit**, gated on an imminent wipe, targeting the *other*
  (larger) cause `doomed_active_overcommit` rather than `unpromotable`.
- Distinct from **SOT-2336** (`deviate_margin`, rejected): the change is scoped to
  the promote/retreat context, not a global commitment band.
- Judged on the SOT-2334 ELO-proxy `R*` / upset-tier NET, not win rate.

## Result — the lever REDISTRIBUTES rating, it does not gain it

Screen (seed 2366, n=16/cell, budget 0.12s, faults=0) over 3 parameterizations —
every config **drops R\*** and the target cause `doomed_active_overcommit` does
**not** fall (rises 14→19 in two of three; flat in the third while R\* tanks):

| arm | R* | upset-loss-rate | doomed_active_overcommit | net |
| --- | --- | --- | --- | --- |
| base | 1511.6 | 0.362 | 14 | −624.8 |
| A (r40/o30/f0.4) | 1504.1 | 0.362 | **19** | −617.8 |
| B (r70/o20/f0.5) | 1467.1 | 0.375 | 14 | −499.8 |
| C (r20/o50/f0.4) | 1481.8 | 0.350 | **19** | −521.1 |

Confirm (independent seeds **12366 / 22366 / 32366**, n=16/cell, faults=0) on the
best-looking arm **C** (`wipe_retreat_bias=20, wipe_overcommit_penalty=50,
active_vulnerable_hp_frac=0.4`):

| metric | base | candC | Δ |
| --- | --- | --- | --- |
| pooled R* | 1499.1 | 1501.6 | **+2.5** (need ≥ +5.0) |
| per-seed R* gain | — | — | **{−30.0, +52.1, −14.8}** (all-up: **No**) |
| upset-tier loss rate | 0.404 | 0.350 | −0.054 |
| upset board_wipe `doomed_active_overcommit` | 59 | 48 | −11 |
| `upset_tier_board_wipe_net` | −1979.3 | −1694.2 | +285 |
| per-seed upset-tier NET | — | — | {+9.2, +251.6, +135.1} |
| **strong-tier wr** | **0.646** | **0.417** | **−0.229** |
| peer-tier wr | 0.521 | 0.500 | −0.021 |
| acquisition wr | 0.535 | 0.451 | −0.084 |
| defensive-tier wr | 0.596 | 0.650 | +0.054 |

`compare` **VERDICT: NON-PROMOTE** — fails the magnitude gate (R\* gain +2.5 <
+5.0) and the confirm-stability gate (2/3 seeds down).

## Mechanism (why it fails)

Unlike the screen (a noisy single seed where the cause even rose), the 3-seed
confirm shows the lever *does* cut weak-tier board_wipe upsets
(`doomed_active_overcommit` 59→48, upset-loss-rate 0.404→0.350, upset-tier NET up
in all 3 seeds). But it buys that by playing too conservatively: retreating off /
refusing to develop the front-line Active **collapses the strong-tier win rate**
(0.646→**0.417**, −0.229; peer −0.021, acquisition −0.084). The lever
**redistributes** rating from the strong/peer tiers to the weak tiers with **no
net R\*** gain (+2.5, within noise, 2/3 seeds down). The `upset_tier_board_wipe_net`
improvement is real here (R\* is flat, not deflated as in SOT-2367) but is not a
rating win — the conservatism that plugs the weak-side wipe leak bleeds an equal-
or-greater amount at the tiers where rating is earned. Consistent with the whole
cycle: SOT-1837/2283 (leaf quality is the binding constraint), SOT-2335/2336/2367
(neither an eval bonus, a decision band, nor a bench-play bias converts the
board_wipe leak into rating).

## Acceptance

- [x] Wipe-risk preventive retreat / anti-overcommit action behaviour implemented,
      gated on an imminent wipe, fixed by 15 unit tests.
- [x] elo_gauntlet screen (3 configs) → confirm (independent 3 seeds) A/B recorded
      (`docs/elo_gauntlet/sot2366_{screen,confirm}_*.jsonl`).
- [x] Non-promotion decided with numerical evidence; champion **byte-identical**
      (`main.py` untouched, PlannerConfig defaults 0 ⇒ `_score_option` unchanged;
      `test_default_is_champion`), lever kept opt-in default OFF (SOT-2367 precedent).
- [x] `docs/ai/experiment_ledger.jsonl` appended (axis, result=rejected, cycle=2).
- [x] No Kaggle submission (parent SOT-2363 only).

**Conclusion:** the wipe-risk conservative-retreat / anti-overcommit lever is
**non-promoted**. It is the clearest evidence yet that the upset-tier board_wipe
leak is *not independently reducible*: cutting it via front-line conservatism
costs at least as much rating at the strong/peer tiers. The next rung must earn
rating without trading away strong-tier commitment — external-knowledge import
(public notebooks / papers) or a leaf-quality improvement, not another
board_wipe-defence action lever.
