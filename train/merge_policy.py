"""Merge sharded policy self-play JSONL into one dataset (SOT-1916).

Companion to train/gen_policy.py, mirroring train/merge_selfplay.py but for the
policy schema ({"s","opts","pi","z"} rows, `policy_feature_version` meta). Every
shard must share the same policy_feature_version; the union is one coherent
dataset (the shards partition the match space disjointly by seed).

Usage:
    python3 train/merge_policy.py --out train/data/policy.jsonl \
        train/data/policy.shard*.jsonl
"""
import argparse
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from agents.policy_features import POLICY_FEATURE_VERSION


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("inputs", nargs="+")
    args = ap.parse_args()

    paths = []
    for pat in args.inputs:
        paths.extend(sorted(glob.glob(pat)) or ([pat] if os.path.exists(pat)
                                                else []))
    if not paths:
        raise SystemExit("no input shards matched")

    rows = []
    matches = faults = 0
    shards = []
    for p in paths:
        with open(p) as f:
            first = True
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if first and "meta" in obj:
                    first = False
                    m = obj["meta"]
                    fv = m.get("policy_feature_version", POLICY_FEATURE_VERSION)
                    if fv != POLICY_FEATURE_VERSION:
                        raise SystemExit(f"{p}: policy_feature_version {fv} != "
                                         f"runtime {POLICY_FEATURE_VERSION}")
                    matches += m.get("matches_played", 0)
                    faults += m.get("faults", 0)
                    shards.append({"path": os.path.basename(p),
                                   "shard_index": m.get("shard_index"),
                                   "samples": m.get("samples")})
                    continue
                first = False
                rows.append(obj)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(json.dumps({"meta": {
            "policy_feature_version": POLICY_FEATURE_VERSION,
            "merged_shards": len(shards), "matches_played": matches,
            "faults": faults, "samples": len(rows), "shards": shards}}) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"merged {len(shards)} shards -> {args.out}: {len(rows)} samples, "
          f"{matches} matches, faults={faults}")


if __name__ == "__main__":
    main()
