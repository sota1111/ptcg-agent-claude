#!/usr/bin/env python3
"""Reproducible, meta-following deck-pool updater for claude (SOT-2055).

Follows the public PTCG-AI-Battle metagame and reorganizes claude's *active deck
pool* from the existing legal deck library — keeping claude's role (upper-meta
coverage + upper-meta resistance), judging on Top10/Top20/Top100 bands + rank +
trend + continuity (not usage alone), bounding one update to <=25% churn, and
saving a rollback manifest.

Reproducible by construction: analysis/selection read the committed snapshots
under ``decks/meta/snapshots`` and are deterministic, so the same inputs + seed
always yield the same plan. ``--fetch`` is the only network path.

Examples
--------
    # inventory the current library (counts, legality, meta mapping)
    python tools/deck_update.py --inventory

    # preview the update WITHOUT changing anything
    python tools/deck_update.py --source https://ptcg-meta.vercel.app --latest --dry-run

    # apply the update (writes the active manifest + rollback manifest)
    python tools/deck_update.py --latest --apply --seed 0

    # roll back to a previous state
    python tools/deck_update.py --rollback decks/meta_active/rollback/<file>.json

    # (best effort, network) refresh the committed snapshots
    python tools/deck_update.py --source https://ptcg-meta.vercel.app --fetch
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
from typing import Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tools import deck_map, deck_selection, meta_analysis  # noqa: E402
from tools import deck_legality  # noqa: E402

SNAP_DIR = os.path.join(REPO, "decks", "meta", "snapshots")
ACTIVE_DIR = os.path.join(REPO, "decks", "meta_active")
ACTIVE_MANIFEST = os.path.join(ACTIVE_DIR, "manifest.json")
ROLLBACK_DIR = os.path.join(ACTIVE_DIR, "rollback")
CANDIDATE_DIR = os.path.join(REPO, "decks", "candidates")


# ----------------------------------------------------------------------------
# snapshot / inventory helpers
# ----------------------------------------------------------------------------
def load_snapshots(snap_dir: str = SNAP_DIR) -> List[Dict[str, object]]:
    files = sorted(glob.glob(os.path.join(snap_dir, "20*.json")))
    snaps = []
    for p in files:
        with open(p, encoding="utf-8") as f:
            snaps.append(json.load(f))
    snaps.sort(key=lambda s: s["date"])
    return snaps


def source_path(row: Dict[str, object]) -> str:
    return os.path.join(REPO, "decks", row["group"], row["file"])


def build_inventory() -> List[Dict[str, object]]:
    """Every legal deck with archetype/meta/role/legality/load status."""
    rows = deck_map.library_rows()
    pool = None
    card_data = True
    try:
        pool = deck_legality.load_card_pool()
    except deck_legality.CardDataUnavailable:
        card_data = False
    out = []
    for r in rows:
        path = source_path(r)
        exists = os.path.exists(path)
        ids = deck_legality.load_deck_ids(path) if exists else []
        legality = None
        if card_data and ids:
            legality = deck_legality.check_deck(ids, pool)
        out.append({
            **r,
            "exists": exists,
            "n_cards": len(ids),
            "deck_hash": _deck_hash(ids) if ids else None,
            "legal": (legality["legal"] if legality else None),
            "legality": legality,
        })
    return out


def _deck_hash(ids: List[int]) -> str:
    import hashlib
    payload = ",".join(str(c) for c in sorted(ids))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def detect_prior_active() -> List[str]:
    """The current active pool: existing meta_active manifest, else the full
    ``decks/candidates`` library (claude's prior pool = all 26 candidate decks)."""
    if os.path.exists(ACTIVE_MANIFEST):
        with open(ACTIVE_MANIFEST, encoding="utf-8") as f:
            m = json.load(f)
        return [d["file"] for d in m.get("decks", [])]
    return sorted(os.path.basename(p) for p in
                  glob.glob(os.path.join(CANDIDATE_DIR, "[0-9][0-9]_*.csv")))


# ----------------------------------------------------------------------------
# plan
# ----------------------------------------------------------------------------
def compute_plan(target_size: Optional[int], max_churn_frac: float,
                 max_per_arch: int, seed: int) -> Dict[str, object]:
    snaps = load_snapshots()
    if not snaps:
        raise SystemExit("no meta snapshots found under decks/meta/snapshots")
    signals = meta_analysis.analyze(snaps)
    # signals is keyed by JP archetype; keep only ones claude maps to.
    rows = deck_map.library_rows()
    prior = detect_prior_active()
    p = deck_selection.plan(rows, signals, prior, target_size=target_size,
                            max_churn_frac=max_churn_frac,
                            max_per_arch=max_per_arch, seed=seed)
    p["snapshot_dates"] = [s["date"] for s in snaps]
    p["as_of"] = snaps[-1]["date"]
    p["signals"] = signals
    return p


def print_plan(p: Dict[str, object]) -> None:
    print("=" * 72)
    print(f"claude meta deck-pool update — DRY RUN (as of {p['as_of']})")
    print(f"reference snapshots: {', '.join(p['snapshot_dates'])}")
    print(f"prior active count : {p['prior_count']}")
    print(f"target size        : {p['target_size']}   "
          f"max change (25%): {p['max_changes']}   "
          f"max per archetype: {p['max_per_arch']}")
    print("-" * 72)
    print(f"ADD ({len(p['added'])}):")
    for f in p["added"]:
        d = p["detail"][f]
        print(f"  + {f}  [{d['meta_score']}]  {d['reason']}")
    print(f"REMOVE ({len(p['removed'])}):")
    for f in p["removed"]:
        d = p["detail"].get(f, {"meta_score": "?", "reason": "not in library"})
        print(f"  - {f}  [{d.get('meta_score')}]  {d.get('reason')}")
    capped = p.get("capped_over_concentration", [])
    if capped:
        print(f"CAPPED (over-concentration, excluded from pool): {capped}")
    print("-" * 72)
    print(f"projected active count: {p['active_count']}   churn: {p['churn']}"
          f"{'  (churn-limited to cap)' if p['churn_limited'] else ''}")
    print("active pool:")
    for f in p["active"]:
        d = p["detail"][f]
        print(f"    {f:44s} [{d['meta_score']:>6}] {d['role']:12s} "
              f"{d['meta_key'] or '(off-meta)'}")
    print("=" * 72)


# ----------------------------------------------------------------------------
# apply / rollback
# ----------------------------------------------------------------------------
def _sync_active_csvs(files: List[str], inv_by_file: Dict[str, Dict[str, object]]) -> None:
    """Make decks/meta_active/*.csv exactly the selected files (copied)."""
    for p in glob.glob(os.path.join(ACTIVE_DIR, "*.csv")):
        os.remove(p)
    for f in files:
        row = inv_by_file[f]
        shutil.copyfile(source_path(row), os.path.join(ACTIVE_DIR, f))


def _next_rollback_path(as_of: str) -> str:
    os.makedirs(ROLLBACK_DIR, exist_ok=True)
    n = 1
    while True:
        cand = os.path.join(ROLLBACK_DIR, f"{as_of}-{n:02d}.json")
        if not os.path.exists(cand):
            return cand
        n += 1


def apply_plan(p: Dict[str, object], seed: int) -> str:
    os.makedirs(ACTIVE_DIR, exist_ok=True)
    inv = {r["file"]: r for r in deck_map.library_rows()}

    # 1) save rollback = the state we are about to overwrite
    prev_manifest = None
    if os.path.exists(ACTIVE_MANIFEST):
        with open(ACTIVE_MANIFEST, encoding="utf-8") as f:
            prev_manifest = json.load(f)
    rollback = {
        "restores_to": ("previous meta_active manifest" if prev_manifest
                        else "full candidate pool (no prior meta_active)"),
        "prior_active": p["prior_active"],
        "previous_manifest": prev_manifest,
        "created_for_as_of": p["as_of"],
    }
    rb_path = _next_rollback_path(p["as_of"])
    with open(rb_path, "w", encoding="utf-8") as f:
        json.dump(rollback, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # 2) write the new manifest
    decks = []
    for f in p["active"]:
        d = p["detail"][f]
        decks.append({
            "file": f,
            "source_group": d["group"],
            "archetype": d["archetype"],
            "meta_key": d["meta_key"],
            "role": d["role"],
            "meta_score": d["meta_score"],
            "reason": d["reason"],
        })
    manifest = {
        "as_of": p["as_of"],
        "seed": seed,
        "snapshot_dates": p["snapshot_dates"],
        "source": "https://ptcg-meta.vercel.app",
        "role": "upper-meta coverage + upper-meta resistance (counters)",
        "prior_count": p["prior_count"],
        "active_count": p["active_count"],
        "target_size": p["target_size"],
        "max_changes": p["max_changes"],
        "churn": p["churn"],
        "churn_limited": p["churn_limited"],
        "added": [{"file": f, "reason": p["detail"][f]["reason"]}
                  for f in p["added"]],
        "removed": [{"file": f,
                     "reason": p["detail"].get(f, {}).get("reason", "off-meta / dropped")}
                    for f in p["removed"]],
        "capped_over_concentration": p.get("capped_over_concentration", []),
        "decks": decks,
        "rollback_manifest": os.path.relpath(rb_path, REPO),
    }
    with open(ACTIVE_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # 3) sync the csvs
    _sync_active_csvs(p["active"], inv)
    return rb_path


def rollback(rollback_file: str) -> None:
    with open(rollback_file, encoding="utf-8") as f:
        rb = json.load(f)
    prev = rb.get("previous_manifest")
    inv = {r["file"]: r for r in deck_map.library_rows()}
    if prev is None:
        # No prior meta_active: remove manifest + csvs (restore to initial).
        if os.path.exists(ACTIVE_MANIFEST):
            os.remove(ACTIVE_MANIFEST)
        for p in glob.glob(os.path.join(ACTIVE_DIR, "*.csv")):
            os.remove(p)
        print(f"rolled back: removed meta_active pool "
              f"(restored to {rb['restores_to']})")
        return
    with open(ACTIVE_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(prev, f, ensure_ascii=False, indent=2)
        f.write("\n")
    _sync_active_csvs([d["file"] for d in prev.get("decks", [])], inv)
    print(f"rolled back: restored meta_active to as_of {prev.get('as_of')}")


# ----------------------------------------------------------------------------
# fetch (network, best effort)
# ----------------------------------------------------------------------------
def fetch_snapshots(source: str, dates: Optional[List[str]], latest_n: int) -> None:
    from tools import meta_fetch
    os.makedirs(SNAP_DIR, exist_ok=True)
    if not dates:
        available = meta_fetch.list_available_dates(source)
        dates = available[-latest_n:] if latest_n else available
    for d in dates:
        try:
            snap = meta_fetch.fetch_daily(d, source)
        except Exception as exc:  # best effort
            print(f"  fetch {d}: FAILED ({exc})")
            continue
        snap["_provenance"] = {"fetched_from": source,
                               "tool": "tools/deck_update.py --fetch"}
        out = os.path.join(SNAP_DIR, f"{d}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"  fetched {d} -> {os.path.relpath(out, REPO)}")


# ----------------------------------------------------------------------------
# inventory printing
# ----------------------------------------------------------------------------
def print_inventory(inv: List[Dict[str, object]]) -> None:
    print(f"deck library inventory — {len(inv)} decks")
    print("-" * 72)
    for r in inv:
        legal = ("legal" if r["legal"] else "ILLEGAL") if r["legal"] is not None \
            else "legality:n/a(no card data)"
        print(f"  {r['file']:44s} {r['group']:10s} n={r['n_cards']:>2} "
              f"{legal:22s} role={r['role']:12s} "
              f"meta={r['meta_key'] or '(off-meta)'}")
    counts = {}
    for r in inv:
        counts[r["role"]] = counts.get(r["role"], 0) + 1
    print("-" * 72)
    print("role counts:", counts)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="https://ptcg-meta.vercel.app",
                    help="meta dashboard base URL (records provenance; network only with --fetch)")
    ap.add_argument("--latest", action="store_true",
                    help="use the latest committed snapshots (default behavior)")
    ap.add_argument("--dry-run", action="store_true",
                    help="preview the update without writing anything")
    ap.add_argument("--apply", action="store_true",
                    help="apply the update (writes active + rollback manifests)")
    ap.add_argument("--inventory", action="store_true",
                    help="print the deck library inventory and exit")
    ap.add_argument("--rollback", metavar="FILE",
                    help="restore a previous state from a rollback manifest")
    ap.add_argument("--fetch", action="store_true",
                    help="best-effort: (re)generate committed snapshots from --source")
    ap.add_argument("--dates", nargs="*", help="explicit snapshot dates for --fetch")
    ap.add_argument("--latest-n", type=int, default=5,
                    help="how many latest daily pages to --fetch (default 5)")
    ap.add_argument("--target-size", type=int, default=None,
                    help="active pool size (default: keep prior count)")
    ap.add_argument("--max-churn-frac", type=float, default=0.25)
    ap.add_argument("--max-per-arch", type=int, default=deck_selection.DEFAULT_MAX_PER_ARCH)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", metavar="PATH", help="write the plan as JSON")
    args = ap.parse_args(argv)

    if args.fetch:
        print(f"fetching snapshots from {args.source} ...")
        fetch_snapshots(args.source, args.dates, args.latest_n)
        return 0

    if args.rollback:
        rollback(args.rollback)
        return 0

    if args.inventory:
        print_inventory(build_inventory())
        return 0

    p = compute_plan(args.target_size, args.max_churn_frac,
                     args.max_per_arch, args.seed)

    if args.json:
        serializable = {k: v for k, v in p.items() if k != "signals"}
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)
            f.write("\n")

    if args.apply:
        rb = apply_plan(p, args.seed)
        print(f"applied. active_count={p['active_count']} churn={p['churn']}")
        print(f"rollback manifest: {os.path.relpath(rb, REPO)}")
        return 0

    # default + --dry-run: preview
    print_plan(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
