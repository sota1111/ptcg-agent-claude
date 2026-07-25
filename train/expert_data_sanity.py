"""H1-H3 vs loss-cause correlation sanity check for expert data (SOT-1914).

Reads a generated/merged expert dataset and reports, for each H1-H3 feature,
its mean among samples flagged with the board-wipe / seed-depletion auxiliary
target vs the rest, plus the Pearson (point-biserial) correlation between the
feature and each binary aux target. This is a sanity check that the SOT-1894
hypotheses actually track the tagged loss cause in the generated data — NOT a
promotion gate. Pure Python (numpy-free), so it runs anywhere the generator
does.

Usage::

    python3 train/expert_data_sanity.py train/data/expert.jsonl
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from agents.expert_features import H_FEATURE_NAMES


def _pearson(xs, ys):
    n = len(xs)
    if n == 0:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def load_rows(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict) and "h" in obj and "aux_wipe" in obj:
                rows.append(obj)
    return rows


def summarize(rows):
    out = {"n_samples": len(rows),
           "n_aux_wipe": sum(1 for r in rows if r.get("aux_wipe")),
           "n_aux_seed": sum(1 for r in rows if r.get("aux_seed")),
           "features": {}}
    for j, name in enumerate(H_FEATURE_NAMES):
        feat = [float(r["h"][j]) for r in rows]
        entry = {}
        for tgt in ("aux_wipe", "aux_seed"):
            lbl = [1.0 if r.get(tgt) else 0.0 for r in rows]
            pos = [f for f, l in zip(feat, lbl) if l == 1.0]
            neg = [f for f, l in zip(feat, lbl) if l == 0.0]
            entry[tgt] = {
                "mean_pos": round(sum(pos) / len(pos), 4) if pos else None,
                "mean_neg": round(sum(neg) / len(neg), 4) if neg else None,
                "pearson_r": round(_pearson(feat, lbl), 4),
            }
        out["features"][name] = entry
    return out


def format_report(summary) -> str:
    lines = [
        f"samples={summary['n_samples']} "
        f"aux_wipe={summary['n_aux_wipe']} aux_seed={summary['n_aux_seed']}",
        "",
        f"{'feature':<22} {'wipe μ+':>8} {'wipe μ-':>8} {'wipe r':>7} "
        f"{'seed μ+':>8} {'seed μ-':>8} {'seed r':>7}",
    ]
    for name in H_FEATURE_NAMES:
        e = summary["features"][name]
        w, s = e["aux_wipe"], e["aux_seed"]
        lines.append(
            f"{name:<22} {str(w['mean_pos']):>8} {str(w['mean_neg']):>8} "
            f"{w['pearson_r']:>7} {str(s['mean_pos']):>8} "
            f"{str(s['mean_neg']):>8} {s['pearson_r']:>7}")
    return "\n".join(lines)


def main_argv(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    ap.add_argument("--json", action="store_true", help="emit JSON summary")
    args = ap.parse_args(argv)
    rows = load_rows(args.path)
    summary = summarize(rows)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(format_report(summary))
    return summary


if __name__ == "__main__":
    main_argv()
