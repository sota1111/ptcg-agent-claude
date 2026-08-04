# SOT-2403 — SO-ISMCTS single shared information-set tree (cycle-3 search-architecture child)

Parent: **SOT-2397** (Kaggle順位向上サイクル 第3次). Axis: **search architecture**
(determinized MCTS → Single-Observer ISMCTS shared information-set tree), the
final escalation rung after cycle-1/2 closed the board-wipe defence family
(SOT-2335/2336/2365/2366/2367) and the leaf-quality axis (SOT-1837/2283).

**Verdict: NON-PROMOTION.** The champion is unchanged (`main.py` byte-identical);
the SO-ISMCTS path ships **opt-in, `PlannerConfig.ismcts` default OFF** as a
closed evidenced axis. No Kaggle submission (parent SOT-2397 owns submission).

## Goal

The champion planner is a **determinized MCTS**: every decision samples
`n_worlds` independent determinizations, runs a **separate search tree per world**
(`_iterate(worlds[iterations % len(worlds)], …)`), and averages root-action
statistics across worlds (`_best_action`). This per-world independent-tree /
cross-world averaging is a textbook source of **strategy fusion** — each world
optimizes as if the hidden information were known, so the agent can pick
mutually inconsistent actions across states it cannot actually distinguish
(Cowling, Powley & Whitehouse 2012, *Information Set Monte Carlo Tree Search*).
The literature reports that a **single shared information-set tree** (ISMCTS)
mitigates strategy fusion and allocates search more efficiently in
imperfect-information card games. This child tests whether that architectural
change lifts the pooled ELO-proxy R* over the determinized champion.

## What was added (additive, opt-in — champion byte-identical)

- **`agents/planner.PlannerConfig.ismcts: bool = False`** — default OFF ⇒ the
  determinized MCTS path is byte-identical and `main.py` / `FABLE_CONFIG` never
  set it (`test_flag_defaults_off`, `test_default_is_champion_path`, `git diff
  origin/main…HEAD -- main.py` empty).
- **`_plan_ismcts` / `_ismcts_iterate` / `_ismcts_select` / `_ismcts_best_action`
  / `_record_root_ismcts`** — a **Single-Observer ISMCTS**: each iteration samples
  ONE determinization from the champion's existing `n_worlds` determinization pool
  and descends a **single shared tree** whose nodes are keyed by the observing
  player's information set. Selection is PUCT restricted to the **legal actions in
  the sampled world**, with the ISMCTS **availability correction** (exploration
  scales with `sqrt(availability count)`, not total visits), so options that are
  legal less often are not unfairly penalized. Root action is chosen from the
  **single shared statistic** (per-world averaging abolished).
- Budget / fallback / RNG discipline is inherited from the champion path: anytime,
  80 %-budget stop, degrade-to-greedy-prior when no world builds, deterministic
  per-seed action (`test_same_seed_same_action`, `test_releases_every_search_state`,
  `test_degrades_to_greedy_prior_when_no_world_builds`).
- **17 unit tests** (`tests/test_ismcts.py`): flag parity, info-set key semantics
  (serial excluded, order-independent multiselect), availability correction,
  opponent-node Q flip, single-shared-statistic root choice, single-tree (not
  n_worlds trees) invariant, scripted-win finding. Full suite **208 green**.

## Architecture rationale (new axis, not a closed-axis re-try)

- **Orthogonal to leaf quality** (SOT-1837 value-net leaf / SOT-2283, CLOSED):
  ISMCTS changes the cross-world **aggregation structure**, not the leaf estimate.
- **Orthogonal to raw `n_worlds`** (SOT-2172, CLOSED): the determinization *pool*
  is unchanged; what changes is one shared tree vs `n_worlds` independent trees.
- **Orthogonal to the board-wipe defence family** (SOT-2335/2336/2365/2366/2367):
  no action-prior or eval-term lever; a pure search-tree topology change.

## A/B result (eval/elo_gauntlet.py, full field incl. elite, faults = 0)

Isolated candidate-vs-field, `--champion-overrides '{"ismcts": true}'`, n = 16/cell,
budget 0.12 s. Pooled R* via the gauntlet's fixed-point performance-rating solver.

**SCREEN** (seed 2403): base R\* **1557.1**, ISMCTS R\* **1474.5**, gain **−82.6**.
ISMCTS regresses at screen — decisively below the ≥ +5.0 gate.

**CONFIRM** (independent seeds 12403 / 22403 / 32403):

| | pooled R\* | per-seed R\* gain |
| --- | --- | --- |
| base | 1509.1 | — |
| ISMCTS | 1496.7 | +7.5 / +51.8 / **−98.1** |
| **gain** | **−12.4** | **not same-direction** |

Per-tier win-rate (confirm, pooled 3 seeds), base → ISMCTS:

| cell | anchor | base wr | ISMCTS wr |
| --- | --- | --- | --- |
| random | 1000 | 0.938 | 0.875 |
| rule | 1230 | 0.583 | 0.625 |
| greedy | 1330 | 0.604 | 0.583 |
| tactical | 1380 | 0.646 | 0.458 |
| mcts_low | 1470 | 0.500 | 0.667 |
| mcts_peer | 1560 | 0.438 | 0.521 |
| mcts_high | 1660 | 0.458 | 0.417 |
| mcts_elite | 1760 | 0.500 | 0.417 |
| **overall** | | **0.583** | **0.570** |

**Promotion gate** (pooled R\* gain ≥ +5.0 AND all seeds same direction AND
faults/budget_violations/fallback = 0): **FAILS** — screen gain −82.6, confirm
pooled gain −12.4, and the confirm seeds split sign (+7.5 / +51.8 / −98.1).
faults = 0 across all 64 cells.

## Mechanism / lesson

SO-ISMCTS **redistributes** rating rather than adding it: it improves some
mid-upset tiers (`mcts_low` 0.500→0.667, `rule` +0.04) but bleeds an equal-or-
greater amount at the cheap-to-hold low anchors (`random` 0.938→0.875,
`tactical` 0.646→0.458) and at the top (`mcts_elite` 0.500→0.417). Net pooled R\*
is slightly negative and, critically, **unstable across seeds** — the sign
depends on the seed, which is the hallmark of a change inside the noise band
rather than a real gain. At this compute budget (0.12 s, small `n_worlds`) the
single shared tree gets fewer *effective* samples per information set than the
determinized ensemble gets per world, so the theoretical strategy-fusion win is
outweighed by higher per-node variance. The strategy-fusion axis is **not
free-lunch at champion budget**; realising it would need a larger search budget
and/or a determinization-consistent leaf, which is out of scope here.

**Champion maintained** — `main.py` byte-identical (`git diff --exit-code`), flag
opt-in default OFF as a closed evidenced axis. 208 unit tests green. No Kaggle
submission (parent SOT-2397 only). Ledger: `result=rejected`. Next rung: the
search-architecture axis is now evidenced-closed at champion budget; remaining
escalation is external-knowledge / higher-budget search, owned by the parent.
