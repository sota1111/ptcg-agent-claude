"""Schema validation for expert-iteration self-play data (SOT-1914).

Checks the invariants the SOT-1911 learning relies on, so a corrupt/partial
dataset fails loudly BEFORE it is fed to GPU training:

- ``f`` (state features) has length ``FEATURE_DIM`` and is finite;
- ``h`` (H1-H3 features) has length ``H_FEATURE_DIM`` and every value is in
  ``[0, 1]``;
- ``pi`` (visit distribution) has matching ``a``/``v``/``p`` lengths, ``p`` sums
  to 1 (within tolerance), and each ``p`` is a valid probability;
- ``y`` (win/loss label) is present and in ``{0.0, 0.5, 1.0}`` — no missing
  labels;
- ``aux_wipe`` / ``aux_seed`` are 0/1.

Meta lines (``{"meta": ...}``) and ``{"match_done": ...}`` markers are skipped.
Exits non-zero on the first batch of violations (capped in the report), so it
doubles as a CI/acceptance gate. ``validate_file`` returns (n_rows, errors) for
programmatic use (tests).

Usage::

    python3 train/validate_expert_data.py train/data/expert.jsonl
"""
import argparse
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from agents.value_features import FEATURE_DIM
from agents.expert_features import H_FEATURE_DIM

_Y_OK = (0.0, 0.5, 1.0)
_P_TOL = 1e-6


def validate_row(row, tol=1e-6):
    """Return a list of error strings for one sample row (empty == valid)."""
    errs = []
    f = row.get("f")
    if not isinstance(f, list) or len(f) != FEATURE_DIM:
        errs.append(f"f length {len(f) if isinstance(f, list) else 'n/a'} "
                    f"!= {FEATURE_DIM}")
    elif any(not isinstance(x, (int, float)) or math.isnan(x)
             or math.isinf(x) for x in f):
        errs.append("f has non-finite value")

    h = row.get("h")
    if not isinstance(h, list) or len(h) != H_FEATURE_DIM:
        errs.append(f"h length {len(h) if isinstance(h, list) else 'n/a'} "
                    f"!= {H_FEATURE_DIM}")
    elif any((not isinstance(x, (int, float))) or x < -tol or x > 1 + tol
             for x in h):
        errs.append("h value out of [0,1]")

    pi = row.get("pi")
    if not isinstance(pi, dict):
        errs.append("pi missing")
    else:
        a, v, p = pi.get("a"), pi.get("v"), pi.get("p")
        if not (isinstance(a, list) and isinstance(v, list)
                and isinstance(p, list)):
            errs.append("pi.a/v/p not all lists")
        elif not (len(a) == len(v) == len(p)) or len(p) < 2:
            errs.append(f"pi length mismatch a={len(a)} v={len(v)} p={len(p)}")
        else:
            if any(x < -tol or x > 1 + tol for x in p):
                errs.append("pi.p has value outside [0,1]")
            s = sum(p)
            if abs(s - 1.0) > max(_P_TOL, tol):
                errs.append(f"pi.p sums to {s:.6f} != 1")

    y = row.get("y")
    if y is None:
        errs.append("y missing")
    elif y not in _Y_OK:
        errs.append(f"y {y} not in {_Y_OK}")

    for k in ("aux_wipe", "aux_seed"):
        if row.get(k) not in (0, 1):
            errs.append(f"{k} {row.get(k)} not 0/1")
    return errs


def validate_file(path, tol=1e-6, max_report=20):
    n_rows = 0
    errors = []
    with open(path) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict) or "meta" in obj \
                    or "match_done" in obj:
                continue
            n_rows += 1
            for e in validate_row(obj, tol=tol):
                if len(errors) < max_report:
                    errors.append(f"line {lineno}: {e}")
    return n_rows, errors


def main_argv(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    ap.add_argument("--tol", type=float, default=1e-6)
    args = ap.parse_args(argv)
    n_rows, errors = validate_file(args.path, tol=args.tol)
    if errors:
        print(f"SCHEMA FAIL: {args.path}: {n_rows} rows, "
              f"{len(errors)} error(s) shown:")
        for e in errors:
            print("  " + e)
        raise SystemExit(1)
    print(f"SCHEMA OK: {args.path}: {n_rows} rows validated "
          f"(f={FEATURE_DIM}, h={H_FEATURE_DIM})")
    return n_rows


if __name__ == "__main__":
    main_argv()
