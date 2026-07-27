"""Multi-signal meta analysis over an ordered list of snapshots (SOT-2055).

The hard requirement: **do not select on usage share alone.** For every
archetype we compute Top10 / Top20 / Top100 as separate bands, plus rank, a
trend slope, continuity across snapshots, and a leaderboard-rank signal (an
archetype can be #1 on the board yet rare in the Top100 — タケルライコex).

Pure/deterministic: given the same snapshots it always returns the same
numbers, so downstream selection is reproducible.
"""
from __future__ import annotations

from typing import Dict, List

from tools import deck_map
from tools import meta_snapshot as ms

# An archetype among the top-N leaderboard teams (the LB Top10 we parse) is a
# "leaderboard leader" — a high-rank signal independent of Top100 usage share.
LB_LEADER_RANK = 10
# Below this Top100 share, a leaderboard leader is flagged low-usage/high-rank.
LOW_USAGE_SHARE = 10.0


def _slope(values: List[float]) -> float:
    """Least-squares slope of ``values`` vs their index (0..n-1)."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, values))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def analyze(snapshots: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    """Return per-archetype signals. ``snapshots`` must be date-ascending."""
    if not snapshots:
        return {}
    latest = snapshots[-1]

    archetypes = set()
    for snap in snapshots:
        archetypes.update(ms.all_archetypes(snap))

    # Best (smallest) leaderboard rank per archetype in the latest snapshot.
    lb_rank: Dict[str, int] = {}
    for row in latest["lb_leaders"]:  # type: ignore[index]
        a = row["archetype"]
        lb_rank[a] = min(lb_rank.get(a, 999), int(row["rank"]))

    result: Dict[str, Dict[str, object]] = {}
    for a in archetypes:
        series = [ms.top100_share(s, a) for s in snapshots]
        present = [1 for v in series if v > 0]
        # trailing consecutive presence in Top100
        consec = 0
        for v in reversed(series):
            if v > 0:
                consec += 1
            else:
                break
        latest_share = ms.top100_share(latest, a)
        best_lb = lb_rank.get(a, 999)
        low_usage_high_rank = (best_lb <= LB_LEADER_RANK
                               and latest_share < LOW_USAGE_SHARE)
        result[a] = {
            "archetype_en": deck_map.META_KEY_EN.get(a, a),
            "latest_top100_share": latest_share,
            "latest_top100_rank": ms.top100_rank(latest, a),
            "latest_top10_share": ms.band_share(latest, "top10", a),
            "latest_top20_share": ms.band_share(latest, "top20", a),
            "peak_top100_share": max(series) if series else 0.0,
            "trend_slope": round(_slope(series), 3),
            "snapshots_present": len(present),
            "snapshots_total": len(snapshots),
            "trailing_consecutive": consec,
            "lb_best_rank": best_lb,
            "low_usage_high_rank": low_usage_high_rank,
            "series": series,
        }
    return result


def meta_score(sig: Dict[str, object]) -> float:
    """Composite, interpretable score combining every band + trend + rank.

    Deliberately weights band concentration (Top10/Top20) and leaderboard rank,
    not just raw Top100 usage, so a low-share board leader still scores.
    """
    s = 0.0
    s += float(sig["latest_top100_share"])
    s += 0.6 * float(sig["latest_top20_share"])
    s += 0.6 * float(sig["latest_top10_share"])
    s += 8.0 * max(0.0, float(sig["trend_slope"]))          # rising meta bonus
    s += 2.0 * float(sig["trailing_consecutive"])           # sticky presence
    best_lb = float(sig["lb_best_rank"])
    if best_lb <= LB_LEADER_RANK:
        s += (LB_LEADER_RANK - best_lb + 1) * 4.0           # board-rank bonus
    return round(s, 3)
