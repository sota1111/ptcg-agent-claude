"""Merge sharded expert-iteration datasets into one training file (SOT-1914).

``train/gen_expert_data.py --n-shards M --shard-index k`` writes one append-only
JSONL per shard (sample rows + ``{"match_done": i}`` markers) plus a
``<shard>.meta.json`` sidecar. This unions the shard rows — dropping any match
with no ``match_done`` marker (interrupted mid-match write) — into a single
dataset with a leading ``{"meta": {...}}`` line, and aggregates the sidecar
throughput (summed matches/faults/samples/gen-seconds, per-shard provenance).
Every shard must agree on ``feature_version`` / ``h_feature_version`` /
``schema_version``.

Usage (from the repo root)::

    python3 train/merge_expert_data.py --out train/data/expert.jsonl \
        train/data/expert.shard*.jsonl
"""
import argparse
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from agents.value_features import FEATURE_VERSION
from agents.expert_features import H_FEATURE_VERSION
from train.gen_expert_data import SCHEMA_VERSION, read_expert_rows


def _load_meta(path: str) -> dict:
    side = path + ".meta.json"
    if os.path.exists(side):
        with open(side) as f:
            return json.load(f)
    return {}


def main_argv(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="train/data/expert.jsonl")
    ap.add_argument("inputs", nargs="+", help="shard JSONL paths (globs ok)")
    args = ap.parse_args(argv)

    paths = []
    for pat in args.inputs:
        paths.extend(sorted(glob.glob(pat)) or [pat])
    seen = set()
    paths = [p for p in paths if not (p in seen or seen.add(p))]

    combined = []
    shard_meta = []
    total_played = total_faults = total_matches_done = 0
    total_gen_seconds = 0.0
    for p in paths:
        rows, completed = read_expert_rows(p)
        meta = _load_meta(p)
        for key, runtime in (("feature_version", FEATURE_VERSION),
                             ("h_feature_version", H_FEATURE_VERSION),
                             ("schema_version", SCHEMA_VERSION)):
            v = meta.get(key, runtime)
            if v != runtime:
                raise SystemExit(f"{p}: {key} {v} != runtime {runtime}")
        combined.extend(rows)
        total_matches_done += len(completed)
        total_played += int(meta.get("matches_played", 0) or 0)
        total_faults += int(meta.get("faults", 0) or 0)
        total_gen_seconds += float(meta.get("gen_seconds", 0.0) or 0.0)
        shard_meta.append({
            "path": os.path.basename(p), "seed": meta.get("seed"),
            "shard_index": meta.get("shard_index"),
            "n_shards": meta.get("n_shards"),
            "matches_done": len(completed), "samples": len(rows),
            "gen_seconds": meta.get("gen_seconds"),
            "games_per_hour": meta.get("games_per_hour"),
        })

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    wins = sum(1 for r in combined if r.get("y") == 1.0)
    aux_wipe = sum(1 for r in combined if r.get("aux_wipe"))
    aux_seed = sum(1 for r in combined if r.get("aux_seed"))
    meta = {
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "h_feature_version": H_FEATURE_VERSION,
        "merged_from": shard_meta, "n_shards_merged": len(paths),
        "matches_done": total_matches_done, "matches_played": total_played,
        "faults": total_faults, "gen_seconds": round(total_gen_seconds, 1),
        "samples": len(combined), "win_samples": wins,
        "aux_wipe_samples": aux_wipe, "aux_seed_samples": aux_seed,
        "games_per_hour": round(total_played / total_gen_seconds * 3600, 1)
        if total_gen_seconds > 0 else 0.0,
    }
    with open(args.out, "w") as f:
        f.write(json.dumps({"meta": meta}) + "\n")
        for r in combined:
            f.write(json.dumps(r) + "\n")
    print(f"merged {len(paths)} shards -> {args.out}: {len(combined)} samples "
          f"({wins} win), matches_done={total_matches_done}, "
          f"faults={total_faults}, gen_seconds={total_gen_seconds:.0f}, "
          f"aux_wipe={aux_wipe} aux_seed={aux_seed}")
    return meta


if __name__ == "__main__":
    main_argv()
