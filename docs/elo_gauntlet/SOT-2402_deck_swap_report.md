# SOT-2402 — Deck-archetype swap A/B (Mega Lucario EX) — NON-PROMOTION

**Cycle 3 (parent SOT-2397). Champion maintained. No Kaggle submission.**

## Axis

The largest untouched, fully-portable lever outside the search/eval policy tuning of prior cycles:
**champion deck archetype exchange**. Every prior cycle froze the 松-lineage `deck.csv` and moved only
policy. External research on the parent (SOT-2397) noted the competition's home-grown top solution runs
`SearchScorer × (Mega) Lucario EX` (660.5μ) and the public rule-based sample also adopts a mega-lucario-ex
deck, suggesting deck-side headroom above our best public 571 / recent submissions 454.7–527.2. Deck lists
are pure card-ID data (no non-portable GPU weights), so the archetype is trivially portable.

- **Champion (base):** current 松-lineage `deck.csv` (Mega Abomasnow ex line), unchanged.
- **Candidate:** `decks/candidates/14_mega_lucario_ex.csv` (Mega Lucario ex, mapped to this repo's card pool).

## Harness (additive, champion-default byte-identical)

`eval/elo_gauntlet.py` gains an additive `--candidate-deck <path>` mode: it swaps ONLY the
champion-under-test's deck while the opponent field/baseline stays pinned to the current `deck.csv`
(preserving the relative-comparison basis). With no flag, behaviour is byte-identical to the prior
gauntlet (covered by `tests/test_elo_gauntlet.py`; `champion_default_byte_identical`). `deck.csv`,
`main.py`, and `agents/evaluator.py` are untouched (`git diff --exit-code origin/main` clean).

## Result (screen → confirm, faults=0)

Full field incl. elite, n=16/cell, champion budget 0.12s. Promotion gate = pooled R\* **non-degradation
AND** a positive gain in the **same direction on every seed**, with faults/budget/fallback = 0.

| Stage | Seeds | Base R\* (松) | Candidate R\* (Mega Lucario) | ΔR\* | Base field wr | Cand field wr | Peer mirror wr (base→cand) |
|---|---|---|---|---|---|---|---|
| screen | 2402 | **1541.7** | **1393.3** | **−148.4** | 0.617 | 0.461 | 0.625 → 0.375 |
| confirm | 12402,22402,32402 | **1524.1** | **1355.7** | **−168.4** | 0.599 | 0.422 | 0.583 → 0.292 |

Per-seed confirm R\*: base {1511.6, 1526.6, 1534.1} vs candidate {1363.3, 1363.3, 1340.5} — the
candidate's **best seed (1363.3) is below the base's worst seed (1511.6)**; degradation is unanimous and
stable across all 3 independent seeds. faults = 0 in every run (the candidate deck played 144–240 matches
cleanly, which doubles as conclusive exec-compat/legality evidence for the mapped deck list).

**Verdict: promotion gate FAILS decisively at both screen and confirm (ΔR\* strongly negative, all seeds
same negative direction).** → **NON-PROMOTION.**

## Mechanism

The candidate's loss profile inverts the champion's. The 松 champion leaks rating through upset-tier
`board_wipe` (89.0% of its losses) but wins the peer/strong tiers (peer wr 0.583, net +207 peer / +326
elite). The Mega Lucario deck instead loses primarily on `prize_race_lost` (153 of 222 losses, 68.9%) and
**collapses in the peer and strong tiers** (peer mirror wr 0.292, mcts_elite wr 0.167), i.e. against
equal-and-stronger search it cannot hold the prize race. The champion's `eval_weights`/竹式 thresholds are
co-tuned to the 松 line; the raw swap loses ~168 R\* before any re-tune could plausibly recover it. Because
the degradation is this large and unanimous (not a marginal miss inside the noise band), an archetype-
conditional bounded re-tune of the eval weights cannot bridge a >150-point pooled gap without effectively
becoming a new deck-specific tuning cycle — out of this leaf's bounded scope — so no re-tune was pursued.

## Disposition

- Champion **maintained**: `deck.csv` / `main.py` / `agents/evaluator.py` byte-identical to origin/main
  (`git diff --exit-code` clean). No `deck.csv` substitution.
- Harness kept as **additive** (`--candidate-deck` A/B mode + tests) for reuse by future deck-swap trials.
- Candidate deck list retained under `decks/candidates/` (unused by the champion path).
- `docs/ai/experiment_ledger.jsonl` appended with `result=rejected`.
- **No Kaggle submission** (submission is owned by the parent SOT-2397 resume run only).

## Net lesson

Deck-archetype swap to the portable Mega Lucario EX list is **not** free headroom at champion compute: the
list underperforms the co-tuned 松 champion by ~168 pooled R\* on every seed, losing the peer/strong-tier
prize race. The deck-swap axis is evidenced-closed for the Mega Lucario candidate; the champion's external
top-solution advantage (660.5μ) rests on `SearchScorer` + deck **jointly**, not the deck list alone. Next
rung: import the SearchScorer-style leaf/eval alongside a deck, or a heavier-compute joint deck+policy
co-tune — not another bare deck substitution at champion budget.
