# decks/meta — meta snapshots & the active pool (SOT-2055)

Reproducible inputs for claude's meta-following deck-pool tool
(`tools/deck_update.py`).

## `snapshots/*.json`

Daily snapshots of the public PTCG-AI-Battle metagame, parsed from
`https://ptcg-meta.vercel.app/daily/<date>.html`. Each snapshot keeps the three
**separate** signals SOT-2055 requires — **LB Top10**, **LB Top20**,
**Top100 全体** — plus the leaderboard leaders (a high-rank / low-share signal).
They are committed so analysis and selection are reproducible without the
network. Regenerate best-effort with:

```bash
python tools/deck_update.py --source https://ptcg-meta.vercel.app --fetch --latest-n 5
```

## `../meta_active/`

The reorganized active pool written by `--apply`: `manifest.json` (as-of date,
prior/active counts, churn, per-deck role + reason, add/remove reasons, capped
decks) plus the selected deck CSVs, and `rollback/` manifests for
`--rollback`.

## claude's role

**Upper-meta coverage + upper-meta resistance.** The pool fields the current top
archetypes *and* keeps a floor of counter decks that answer them; selection
weighs Top10/Top20/Top100 bands, rank, trend and continuity — never usage share
alone. Full write-up: `docs/deck_pool_meta_2026-07.md`.
