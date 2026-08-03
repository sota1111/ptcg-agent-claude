# SOT-2336 — strong-opponent attack lever (cycle-1 attack child)

Parent: **SOT-2332** (Kaggle順位向上サイクル 第1次). Dependency: **SOT-2334**
(ELO-consistent local eval harness). Sibling: **SOT-2335** (defence child).

**Verdict: NON-PROMOTION.** The champion is unchanged (`main.py` byte-identical);
the new opponent cell and the A/B machinery are additive **diagnostic tooling**
only. No Kaggle submission (parent SOT-2332 owns submission).

## Goal

On an ELO ladder, beating a genuinely strong opponent earns the most rating
(`K·(1−E)`, E small). The SOT-2334 field topped out at a same-budget peer mirror
plus `mcts@2.5×` — no *external-class* reference. This child (1) adds a truly
strong reference opponent to the gauntlet and (2) tries an **attack lever** to
convert more of those high-value wins, judged on the SOT-2334 ELO-proxy `R*`.

## What was added (additive, opt-in)

- **`mcts_elite` cell** — `eval/elo_gauntlet.build_field(include_elite=True)`:
  the same search agent given `6×` the champion's per-move budget (deep search),
  anchored at **1760** (well above where the champion converges ⇒ a *strong*,
  non-upset tier: the cell where a win EARNS the most rating). `--no-elite`
  reproduces the exact SOT-2334 field.
- **`ATTACK_LEVER = {"deviate_margin": 0.02}`** — the candidate champion diff,
  applied only via `--attack-lever` / `--champion-overrides` in the eval A/B.
  `main.py` (`deviate_margin=0.1`) is never touched.
- **`compare` subcommand** — pure A/B judge: pooled & per-seed `R*` for both
  arms, acquisition-tier (peer/strong/elite) win rate, defensive-tier
  (weak/mid/near_peer) win-rate guard, PROMOTE/NON-PROMOTE verdict.

## Lever rationale (new evidence, not a closed-axis re-try)

`deviate_margin=0.1` is the SOT-1672 *conservatism band*: MCTS must beat the
1-ply greedy-prior action by >0.1 on the value scale before the champion leaves
the prior. Hypothesis: that band was tuned to suppress MCTS **noise** against the
old field; against a genuinely strong opponent the greedy prior's shallow read
is itself more often wrong, so the band over-suppresses exactly the
MCTS-discovered lines that would beat strong search. Lowering it (0.1→0.02) is a
**qualitative change to which action the champion commits to** — orthogonal to
the closed axes: learned value-net leaf eval (SOT-1837/2283, rejected), belief
width `n_worlds` (SOT-2172, rejected), and raw compute. The ELO-proxy `R*` nets
strong-tier acquisition against any new weak-tier upset-loss leak automatically.

## Result — the lever does NOT convert; it drains `R*`

Baseline champion (final run, seeds 43407/55501/67703, n=36/cell, faults=0),
`R*=1466.3`. The acquisition tiers are **already net-positive** — the champion is
not losing rating at the top of the field:

| cell | tier | anchor | wr | net @R* |
| --- | --- | --- | --- | --- |
| mcts_peer | peer | 1560 | 0.500 | +151.7 |
| mcts_high | strong | 1660 | 0.444 | +227.6 |
| **mcts_elite** | **elite** | **1760** | **0.528** | **+428.7** |

The champion actually **wins** the elite cell. The rating leak is entirely on the
**upset tiers** (rule/greedy/tactical), NET **−718.2**, losses **94.0%
board-wipe** — i.e. a *defensive* problem (SOT-2335 territory), not an attack one.

Attack-lever A/B (`compare`, K=32; promotion needs pooled `R*` gain ≥ +5.0 **and**
every shared seed up **and** defensive-tier wr not down > 0.03):

| run | seeds | pooled R* gain | per-seed gain | all seeds up | verdict |
| --- | --- | --- | --- | --- | --- |
| screen   | 2336, 12336        | **−55.1** | {−88.6, −45.7} | No | NON-PROMOTE |
| confirmv2 | 3407, 5501, 7703  | **−16.8** | {0.0, −60.1, +10.2} | No | NON-PROMOTE |
| final    | 43407, 55501, 67703 | **−36.0** | {+29.5, −108.4, −29.5} | No | NON-PROMOTE |

Every independent-seed run drops `R*`. The lever fails on both the magnitude gate
(gain < +5.0, in fact negative) and the confirm-stability gate (not all seeds up).

## Mechanism (why it fails)

Lowering the commitment band makes the champion abandon the greedy-prior action
more often, but the deeper MCTS read it defers to is **not reliably better** at
this compute — so it trades sound prior actions for noisier search actions and
loses rating on net. Consistent with SOT-1837/2283 (value/rollout quality is the
binding leaf constraint) and SOT-2334's core finding: the champion already earns
rating at peer→elite; what drains it is upset **losses** to weaker opponents
(board-wipe), which no *attack* lever can fix — it is a defensive axis.

## Acceptance

- [x] Truly strong external-class reference opponent added (`mcts_elite`, 6×, anchor 1760).
- [x] Acquisition lever implemented as a champion diff with new (non-closed-axis) rationale.
- [x] screen→confirm run on independent seeds via the SOT-2334 ELO-proxy.
- [x] Judgment + evidence recorded here and in `docs/ai/experiment_ledger.jsonl`.
- [x] Non-promotion ⇒ champion reverted/untouched (`main.py` byte-identical); eval infra kept additive.
- [x] Ledger appended.

**Conclusion:** the attack lever is **non-promoted**. The elite cell is retained
as a permanent diagnostic tier (it confirms the champion is already strong at the
top of the field), and the next rating gain must come from the **defensive** axis
(cutting weak-tier board-wipe upset losses), not from the decision-commitment band.
