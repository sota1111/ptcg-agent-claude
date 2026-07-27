# Meta-following deck-pool reorg — ptcg-agent-claude (SOT-2055)

Reorganize claude's `decks/candidates` deck-selection & opponent field to follow
the public PTCG-AI-Battle metagame. Sister of SOT-2050 (松/matsu). **Deck count
is fully delegated to this Issue** — no preservation/rotation constraint is
applied; the pool is reorganized from the existing legal library.

Source of truth: <https://ptcg-meta.vercel.app> `daily/<date>.html` pages,
parsed into committed snapshots. As-of **2026-07-27**.

## 1. Current pool inventory (before)

`decks/candidates/` = **26** legal decks (25 Turin/NAIC 2026 tournament lists +
`26_stw_champion.csv`, the shared matsu/take/ume champion = root `deck.csv`). All
26 pass legality (60 cards, ≤4 same name, ≤1 ACE SPEC, every id in the engine
pool). Run `python3 tools/deck_update.py --inventory`.

Role map (`tools/deck_map.py`, curated 2026-07-27): 9 upper_meta, 1
low_usage_top, 1 emerging, 5 counter, 10 baseline.

### Near-duplicate / over-concentration detection
- **ドラパルトex / Dragapult ex ×5**: `01`, `03`, `04`, `05` (Dudunsparce
  variant), `22` (NAIC 2nd). Heavily over-concentrated.
- **Nのゾロアークex ×2**: `07` (baseline), `24` (counter, ex NAIC 10th).
- **Slowking ×2** (off-meta): `09`, `23`. **Lillie's Clefairy ×2** (off-meta):
  `11`, `21`.

## 2. Existing role

The `decks/candidates` field had no explicit "pool role" doc; the repo used it as
the SOT-1794 deck-selection field + SOT-1896 opponent pool. This Issue makes the
role explicit (now in `README.md` and `decks/meta/README.md`): **upper-meta
coverage + upper-meta resistance**, board-leader + baseline anchors for
diversity, champion `26_stw_champion.csv` always retained.

## 3. Meta analysis (Top10/Top20/Top100 kept separate)

Five committed snapshots (2026-07-14, -20, -25, -26, -27). Each keeps **LB
Top10, LB Top20, Top100 全体** as *separate* signals plus the leaderboard
leaders. Per-archetype signals (`tools/meta_analysis.py`): latest share/rank per
band, peak share, least-squares **trend slope**, **continuity**
(snapshots-present / trailing-consecutive), best **LB rank**, and a
`low_usage_high_rank` flag.

Latest Top100 (2026-07-27): マリィのオーロンゲex 54% (#1), フーディン 26% (#2),
イワパレス 6%, ドラパルトex 4%, ロケット団のワナイダー 3%, シロナのガブリアスex 3%,
**タケルライコex 1% (Top100 #7) yet LB #7** — the canonical "usage alone is
insufficient" case: it is a board leader despite a 1% Top100 share, so it is kept
via the `low_usage_top` role, not its share.

## 4–5. Add / remove selection (reasons recorded)

Selection (`tools/deck_selection.py`) is coverage-first (one best deck per
*present* meta archetype), then the board-leader, then role-minimum counters
(≥3) and baselines (≥2), then fill by a composite meta score, all under a hard
**≤2 per archetype** cap. Guardrails: judge on bands/rank/trend/continuity (not
usage alone), avoid over-concentration, bound one update to **≤25% churn**.

**Result (seed 0, as-of 2026-07-27):** prior 26 → active **23**, churn **3**
(≤ max 6). No adds (every present archetype is already covered by the existing
library); removals are the 3 surplus Dragapult variants over the per-archetype
cap:

| Removed | Reason |
| --- | --- |
| `01_dragapult.csv` | ドラパルトex over-concentration (cap 2); 2 stronger Dragapult decks retained |
| `05_dragapult_dudunsparce.csv` | same — surplus Dragapult variant |
| `22_dragapult_ex_naic_2nd.csv` | same — surplus Dragapult variant |

Removals are **not** made on low usage alone: off-meta baselines (Hydrapple,
Ogerpon Box, Slowking, Ethan's Typhlosion, both Lillie's Clefairy) are *kept* for
diversity; only the over-concentrated archetype is trimmed. Dragapult stays
represented by its 2 highest-scoring lists (`03`, `04`).

## 6. Representative-deck evaluation

`eval/eval_meta_pool.py` pilots every active deck (greedy, seat-alternating,
multi-seed) against 3 representative meta decks — max-share
(`15_marnie_s_grimmsnarl_ex`), #2 (`12_alakazam_dudunsparce`), board-leader
(`02_raging_bolt_ogerpon`) — reporting win rate + Wilson 95% CI. Latest run:
**23 active decks, 0 faults** (all load, are engine-legal, and produce recorded
head-to-head results). Output: `eval/results/sot2055/pool_vs_representatives.json`.

## 7. Apply + rollback

`--apply` wrote `decks/meta_active/` (the 23 selected CSVs + `manifest.json` with
per-deck role/reason and add/remove reasons) and a rollback manifest
`decks/meta_active/rollback/2026-07-27-01.json`. `--rollback <file>` restores the
prior state. Re-applying is a fixed point (churn 0) — idempotent.

## 8. Reproducibility

- Deterministic: analysis/selection read committed snapshots; same input + seed
  ⇒ identical plan (unit test `test_deterministic`).
- `--dry-run` previews without writing; `--apply` is explicit; rollback restores.
- `--fetch` is the only network path (best-effort snapshot refresh).
- Tests: `tests/test_deck_pool_meta.py` (17) + full suite (138) green;
  `eval/deck_validator.py` 50/50 decks valid.

## Acceptance criteria

- [x] Latest meta snapshot obtained; Top10/Top20/Top100 as separate signals
- [x] Judged on rank / trend / continuity, not usage alone (タケルライコ kept via LB rank)
- [x] Existing role documented (README + decks/meta/README)
- [x] Deck count before/after recorded (26 → 23; count delegated to claude)
- [x] Duplicates/near-duplicates detected; add/remove reasons recorded
- [x] New/all active decks pass legality, all loadable, representative eval run (0 faults)
- [x] `--dry-run` preview, rollback possible, reproducible, existing + added tests pass
