"""Meta-driven deck-pool tooling (SOT-2055).

Reproducible utilities that follow the public PTCG AI Battle metagame
(https://ptcg-meta.vercel.app) and reorganize claude's deck pool from the
existing legal deck library. The analysis/selection path is deterministic and
reads committed snapshots; network access is confined to ``meta_fetch``.
"""
