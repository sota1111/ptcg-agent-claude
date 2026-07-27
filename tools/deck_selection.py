"""Deterministic meta-driven deck-pool selection (SOT-2055).

Given the analyzed meta signals and claude's legal deck library, build the new
*active pool* and explain every keep / add / remove with a reason. Pure and
deterministic: same snapshots + same knobs => same plan (no RNG; ``seed`` only
salts tie-breaks so a caller can request an alternative deterministic ordering).

Guardrails encoded here (from SOT-2055 acceptance):
* keep claude's role — upper-meta coverage **and** upper-meta resistance
  (counters) — via role-coverage minimums;
* judge on bands/rank/trend/continuity, not usage alone (``meta_analysis``);
* avoid over-concentrating one archetype (``max_per_arch``);
* keep the effective deck count (``target_size``, default = prior size);
* bound one update to ``max_churn_frac`` of the prior pool (default 25%).
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Optional

from tools import meta_analysis

# Role floors so the pool never loses claude's identity.
MIN_COUNTERS = 3
MIN_BASELINE = 2
DEFAULT_MAX_PER_ARCH = 2


def _tiebreak(file: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{file}".encode()).hexdigest()


def score_library(rows: List[Dict[str, object]],
                  signals: Dict[str, Dict[str, object]]) -> List[Dict[str, object]]:
    """Attach a meta score + explanation to every library deck row."""
    scored = []
    for r in rows:
        mk = r.get("meta_key")
        sig = signals.get(mk) if mk else None
        base = meta_analysis.meta_score(sig) if sig else 0.0
        role = r.get("role")
        role_bonus = {
            "upper_meta": 6.0,
            "low_usage_top": 10.0,   # board leaders must survive low share
            "emerging": 5.0,
            "counter": 8.0,          # claude's role: upper-meta resistance
            "baseline": 1.0,
        }.get(role, 0.0)
        score = round(base + role_bonus, 3)
        scored.append({**r, "meta_score": score, "meta_base": base,
                       "signals": sig})
    return scored


def _reason(r: Dict[str, object]) -> str:
    sig = r.get("signals")
    mk = r.get("meta_key")
    role = r.get("role")
    if sig:
        return (f"{role}; {mk} (Top100 {sig['latest_top100_share']}% "
                f"rank#{sig['latest_top100_rank']}, Top20 {sig['latest_top20_share']}%, "
                f"Top10 {sig['latest_top10_share']}%, trend {sig['trend_slope']}, "
                f"present {sig['snapshots_present']}/{sig['snapshots_total']}, "
                f"LB#{sig['lb_best_rank']})")
    return f"{role}; off-meta (no current Top100 presence)"


def plan(rows: List[Dict[str, object]],
         signals: Dict[str, Dict[str, object]],
         prior_active: List[str],
         target_size: Optional[int] = None,
         max_churn_frac: float = 0.25,
         max_per_arch: int = DEFAULT_MAX_PER_ARCH,
         seed: int = 0) -> Dict[str, object]:
    """Compute the reorganized active pool + keep/add/remove reasons.

    Coverage-first: one best deck per *present* meta archetype (breadth), then
    the board-leader deck, role-minimum counters/baselines, then fill by score —
    always under a hard per-archetype cap so no single archetype crowds the pool.
    """
    prior = list(prior_active)
    if target_size is None:
        target_size = len(prior)

    scored = score_library(rows, signals)
    by_file = {r["file"]: r for r in scored}
    prior_set = set(prior)

    # Ties are broken toward stability: an equally-scored incumbent beats a
    # newcomer, so the tool never churns decks sideways just to swap variants.
    def order_key(r):
        return (-r["meta_score"], 0 if r["file"] in prior_set else 1,
                _tiebreak(r["file"], seed))

    ranked = sorted(scored, key=order_key)

    selected: List[str] = []
    selected_set = set()
    arch_count: Dict[str, int] = {}
    capped: List[str] = []

    def can_take(r) -> bool:
        mk = r.get("meta_key")
        return not (mk and arch_count.get(mk, 0) >= max_per_arch)

    def take(r) -> bool:
        if r["file"] in selected_set:
            return False
        if not can_take(r):
            if r["file"] not in capped:
                capped.append(r["file"])
            return False
        selected.append(r["file"])
        selected_set.add(r["file"])
        mk = r.get("meta_key")
        if mk:
            arch_count[mk] = arch_count.get(mk, 0) + 1
        return True

    # 1) Coverage: one best deck per meta archetype that is currently *present*
    #    (in the Top100, trending up, or a board leader) — breadth before depth.
    present = [mk for mk, s in signals.items()
               if (float(s["latest_top100_share"]) > 0
                   or float(s["trend_slope"]) > 0
                   or int(s["lb_best_rank"]) <= meta_analysis.LB_LEADER_RANK)]
    present.sort(key=lambda mk: -meta_analysis.meta_score(signals[mk]))
    for mk in present:
        best = next((r for r in ranked if r.get("meta_key") == mk), None)
        if best:
            take(best)

    # 2) The board-leader (low-usage/high-rank) deck must survive.
    for r in ranked:
        if r.get("role") == "low_usage_top":
            take(r)

    # 3) Role minimums: counters (claude's resistance role) and baselines.
    for r in [x for x in ranked if x.get("role") == "counter"][:MIN_COUNTERS]:
        take(r)
    for r in [x for x in ranked if x.get("role") == "baseline"][:MIN_BASELINE]:
        take(r)

    # 4) Fill the rest by score up to target_size (respecting the per-arch cap).
    for r in ranked:
        if len(selected) >= target_size:
            break
        take(r)

    # 5) Bound churn vs the prior pool. Swap the weakest newcomer for the
    #    strongest restorable incumbent (one that won't exceed the per-arch cap)
    #    until total change <= max_changes. Each swap keeps the pool size fixed.
    max_changes = int(max_churn_frac * len(prior))

    def current_churn() -> int:
        return (len([f for f in selected_set if f not in prior_set])
                + len([f for f in prior_set if f not in selected_set]))

    churn_limited = False
    if current_churn() > max_changes:
        churn_limited = True
        while current_churn() > max_changes:
            newcomers = sorted([f for f in selected_set if f not in prior_set],
                               key=lambda f: (by_file[f]["meta_score"],
                                              _tiebreak(f, seed)))
            candidates = sorted([f for f in prior_set if f not in selected_set],
                                key=lambda f: (-by_file.get(f, {}).get("meta_score", 0.0),
                                               _tiebreak(f, seed)))
            if not newcomers:
                break
            newcomer = newcomers[0]
            # drop the weakest newcomer first, freeing its archetype slot
            selected.remove(newcomer)
            selected_set.discard(newcomer)
            nmk = by_file[newcomer].get("meta_key")
            if nmk:
                arch_count[nmk] -= 1
            # restore the strongest incumbent that fits the cap
            restored = False
            for inc in candidates:
                row = by_file.get(inc)
                if row is not None and take(row):
                    restored = True
                    break
            if not restored:
                # no restorable incumbent → pool shrinks by one; stop to avoid
                # draining the pool below a usable size.
                break

    selected_sorted = sorted(selected,
                             key=lambda f: (-by_file[f]["meta_score"],
                                            _tiebreak(f, seed)))
    detail = {f: {
        "archetype": by_file[f]["archetype"],
        "meta_key": by_file[f].get("meta_key"),
        "role": by_file[f].get("role"),
        "group": by_file[f].get("group"),
        "meta_score": by_file[f]["meta_score"],
        "reason": _reason(by_file[f]),
    } for f in by_file}

    return {
        "prior_active": prior,
        "prior_count": len(prior),
        "active": selected_sorted,
        "active_count": len(selected_sorted),
        "added": [f for f in selected_sorted if f not in prior],
        "removed": [f for f in prior if f not in selected_set],
        "capped_over_concentration": capped,
        "churn": len([f for f in selected_sorted if f not in prior])
                 + len([f for f in prior if f not in selected_set]),
        "max_changes": max_changes,
        "churn_limited": churn_limited,
        "target_size": target_size,
        "max_per_arch": max_per_arch,
        "detail": detail,
    }
