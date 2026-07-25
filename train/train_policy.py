"""Policy-prior trainer (SOT-1916 expert iteration).

Loads the self-play policy records (train/gen_policy.py JSONL), trains the
per-option scorer to match the champion's MCTS root visit distribution π
(masked softmax cross-entropy over each decision's options), exports the weights
as dependency-free JSON (agents/policy_net.py schema), and runs the train-vs-
exported-inference CONSISTENCY check (SOT-1837 "一致テスト" for the policy head):
the pure-Python PolicyNet reloaded from JSON must reproduce the trainer's own
per-option logits to within a tolerance.

Two backends, identical architecture and export format:
  - ``--backend torch`` (default here): trains the MLP with torch on GPU (the
    RTX 3080 Ti path), then copies the weights into the pure-Python PolicyNet.
  - ``--backend python``: stdlib softmax-CE SGD (agents/policy_net), for the
    GPU-less container.

Usage (from the repo root):
    python3 train/train_policy.py --data train/data/policy.jsonl \
        --out train/weights/policy.json --backend torch \
        --hidden 64 --epochs 200 --lr 0.01
"""
import argparse
import json
import math
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from agents.policy_features import (POLICY_FEATURE_VERSION, POLICY_INPUT_DIM,
                                    OPTION_BLOCK_DIM, STATE_DIM)
from agents.policy_net import PolicyNet, softmax


def load_data(path: str):
    """Return (decisions, meta). Each decision is (X, pi) where X is a list of
    per-option input vectors (state ++ option block) and pi the visit shares."""
    decisions = []
    meta = {}
    with open(path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if i == 0 and "meta" in obj:
                meta = obj["meta"]
                continue
            s = obj["s"]
            opts = obj["opts"]
            pi = obj["pi"]
            X = [list(s) + list(block) for block in opts]
            for x in X:
                if len(x) != POLICY_INPUT_DIM:
                    raise ValueError(f"input dim {len(x)} != {POLICY_INPUT_DIM}")
            decisions.append((X, [float(p) for p in pi]))
    fv = meta.get("policy_feature_version", POLICY_FEATURE_VERSION)
    if fv != POLICY_FEATURE_VERSION:
        raise ValueError(f"data policy_feature_version {fv} != runtime "
                         f"{POLICY_FEATURE_VERSION}")
    return decisions, meta


def split(decisions, val_frac, rng):
    d = list(decisions)
    rng.shuffle(d)
    n_val = int(len(d) * val_frac)
    return d[n_val:], d[:n_val]


def ce_loss_python(net: PolicyNet, decisions) -> float:
    if not decisions:
        return 0.0
    s = 0.0
    for X, pi in decisions:
        p = softmax(net.logits(X))
        s += -sum(pi[k] * math.log(max(p[k], 1e-12)) for k in range(len(X)))
    return s / len(decisions)


def top1_agree(net: PolicyNet, decisions) -> float:
    """Fraction of decisions where argmax(prior) == argmax(π) — the metric that
    actually matters for a prior (does it point the search at the same move)."""
    if not decisions:
        return 0.0
    hit = 0
    for X, pi in decisions:
        logits = net.logits(X)
        if max(range(len(X)), key=lambda k: logits[k]) == \
                max(range(len(X)), key=lambda k: pi[k]):
            hit += 1
    return hit / len(decisions)


def train_python(train, val, hidden, epochs, lr, l2, seed):
    rng = random.Random(seed)
    net = PolicyNet.init(hidden, rng, dim=POLICY_INPUT_DIM)
    order = list(range(len(train)))
    for ep in range(epochs):
        rng.shuffle(order)
        tot = 0.0
        for idx in order:
            X, pi = train[idx]
            tot += net.train_decision(X, pi, lr, l2)
        if (ep + 1) % max(1, epochs // 5) == 0 or ep == 0:
            print(f"  epoch {ep + 1}/{epochs} train_ce~{tot / len(train):.4f} "
                  f"val_ce={ce_loss_python(net, val):.4f} "
                  f"val_top1={top1_agree(net, val):.3f}", flush=True)
    return net


def _pad_batch(decisions, K, device, torch):
    import math as _m
    N = len(decisions)
    X = torch.zeros((N, K, POLICY_INPUT_DIM), dtype=torch.float32)
    PI = torch.zeros((N, K), dtype=torch.float32)
    M = torch.zeros((N, K), dtype=torch.float32)
    for i, (opts, pi) in enumerate(decisions):
        for k in range(min(K, len(opts))):
            X[i, k] = torch.tensor(opts[k], dtype=torch.float32)
            PI[i, k] = pi[k]
            M[i, k] = 1.0
    return X.to(device), PI.to(device), M.to(device)


def train_torch(train, val, hidden, epochs, lr, l2, seed, batch=4096):
    import torch
    torch.manual_seed(seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    K = max(len(X) for X, _ in train)
    print(f"  torch backend on {dev}, max_options K={K}", flush=True)
    model = torch.nn.Sequential(
        torch.nn.Linear(POLICY_INPUT_DIM, hidden), torch.nn.Tanh(),
        torch.nn.Linear(hidden, 1)).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=l2)
    Xtr, PItr, Mtr = _pad_batch(train, K, dev, torch)
    rng = random.Random(seed)
    idx = list(range(len(train)))
    for ep in range(epochs):
        rng.shuffle(idx)
        model.train()
        for b0 in range(0, len(idx), batch):
            bi = torch.tensor(idx[b0:b0 + batch], device=dev)
            xb, pib, mb = Xtr[bi], PItr[bi], Mtr[bi]
            logits = model(xb).squeeze(-1)
            logits = logits.masked_fill(mb == 0, -1e9)
            logp = torch.log_softmax(logits, dim=1)
            loss = -(pib * logp).sum(dim=1).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
        if (ep + 1) % max(1, epochs // 10) == 0 or ep == 0:
            model.eval()
            with torch.no_grad():
                lg = model(Xtr).squeeze(-1).masked_fill(Mtr == 0, -1e9)
                tr_ce = -(PItr * torch.log_softmax(lg, 1)).sum(1).mean().item()
            print(f"  epoch {ep + 1}/{epochs} train_ce={tr_ce:.4f}", flush=True)
    lin1, lin2 = model[0], model[2]
    W1 = lin1.weight.detach().cpu().tolist()
    b1 = lin1.bias.detach().cpu().tolist()
    W2 = lin2.weight.detach().cpu().tolist()[0]
    b2 = lin2.bias.detach().cpu().tolist()[0]
    net = PolicyNet(W1, b1, W2, b2, input_dim=POLICY_INPUT_DIM)
    # torch-forward vs pure-python-forward logit parity on a val sample.
    if val:
        flat = [x for X, _ in val[:200] for x in X]
        with torch.no_grad():
            tv = model(torch.tensor(flat, dtype=torch.float32,
                                    device=dev)).squeeze(-1).cpu().tolist()
        gap = max(abs(tv[i] - net.forward(flat[i])) for i in range(len(flat)))
        print(f"  torch->python logit max gap {gap:.2e}", flush=True)
    return net


def consistency_check(net: PolicyNet, out_path: str, decisions, tol: float):
    reloaded = PolicyNet.load(out_path)
    flat = [x for X, _ in decisions[:200] for x in X]
    if not flat:
        return 0.0
    gap = max(abs(net.forward(x) - reloaded.forward(x)) for x in flat)
    status = "OK" if gap <= tol else "FAIL"
    print(f"consistency (train-forward vs reloaded inference): "
          f"max gap {gap:.2e} tol {tol:.0e} -> {status}", flush=True)
    if gap > tol:
        raise SystemExit(f"consistency check FAILED: {gap} > {tol}")
    return gap


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="train/data/policy.jsonl")
    ap.add_argument("--out", default="train/weights/policy.json")
    ap.add_argument("--backend", choices=("python", "torch"), default="torch")
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=200)
    ap.add_argument("--lr", type=float, default=0.01)
    ap.add_argument("--l2", type=float, default=1e-5)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=1916)
    ap.add_argument("--tol", type=float, default=1e-4)
    args = ap.parse_args()

    decisions, meta = load_data(args.data)
    if not decisions:
        raise SystemExit(f"no decisions in {args.data}")
    rng = random.Random(args.seed)
    train, val = split(decisions, args.val_frac, rng)
    print(f"TRAIN backend={args.backend} decisions={len(decisions)} "
          f"(train {len(train)} / val {len(val)}) input_dim={POLICY_INPUT_DIM} "
          f"(state {STATE_DIM} + option {OPTION_BLOCK_DIM}) "
          f"hidden={args.hidden} epochs={args.epochs} lr={args.lr}", flush=True)

    trainer = train_torch if args.backend == "torch" else train_python
    net = trainer(train, val, args.hidden, args.epochs, args.lr, args.l2,
                  args.seed)
    print(f"final val_ce={ce_loss_python(net, val):.4f} "
          f"val_top1_agree={top1_agree(net, val):.3f} "
          f"(uniform_ce~{_uniform_ce(val):.4f})", flush=True)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    net.save(args.out)
    print(f"wrote weights -> {args.out}", flush=True)
    consistency_check(net, args.out, val or train, args.tol)


def _uniform_ce(decisions) -> float:
    """CE of a uniform prior — the baseline the net must beat to be useful."""
    if not decisions:
        return 0.0
    s = 0.0
    for X, pi in decisions:
        u = 1.0 / len(X)
        s += -sum(pi[k] * math.log(u) for k in range(len(X)))
    return s / len(decisions)


if __name__ == "__main__":
    main()
