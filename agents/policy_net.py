"""Pure-Python policy-prior network (SOT-1916) — the canonical forward pass.

A one-hidden-layer MLP (input -> H tanh -> 1 linear) that scores ONE option:
`forward(x)` returns a raw logit. A selection's prior is `softmax` over its
options' logits (agents/planner.py:_root_candidates applies the planner's own
temperature). Implemented in the standard library only (no numpy / torch), so a
net trained on GPU (train/train_policy.py) and reloaded for pure-Python
inference (agents/learned_prior.py) produces identical logits — the SOT-1837
"一致テスト" carried over to the policy head.

Weights serialize to a plain JSON dict (W1: H x D, b1: H, W2: H, b2: scalar),
so the exported artifact is diffable and dependency-free on the submission path.
"""
import json
import math

from .policy_features import POLICY_FEATURE_VERSION, POLICY_INPUT_DIM


def softmax(logits, temperature: float = 1.0) -> list:
    if not logits:
        return []
    t = max(temperature, 1e-6)
    m = max(logits)
    exps = [math.exp((z - m) / t) for z in logits]
    s = sum(exps)
    return [e / s for e in exps]


class PolicyNet:
    """input(D) -> hidden(H, tanh) -> output(1, linear logit) per-option scorer."""

    def __init__(self, W1, b1, W2, b2, input_dim=None, feature_version=None):
        self.W1 = [list(row) for row in W1]
        self.b1 = list(b1)
        self.W2 = list(W2)
        self.b2 = float(b2)
        self.hidden = len(self.b1)
        self.input_dim = input_dim if input_dim is not None else (
            len(self.W1[0]) if self.W1 else 0)
        self.feature_version = (POLICY_FEATURE_VERSION if feature_version is None
                                else feature_version)

    # ---- construction ----------------------------------------------------

    @classmethod
    def init(cls, hidden: int, rng, dim: int = POLICY_INPUT_DIM) -> "PolicyNet":
        s1 = math.sqrt(1.0 / max(1, dim))
        s2 = math.sqrt(1.0 / max(1, hidden))
        W1 = [[rng.uniform(-s1, s1) for _ in range(dim)] for _ in range(hidden)]
        b1 = [0.0 for _ in range(hidden)]
        W2 = [rng.uniform(-s2, s2) for _ in range(hidden)]
        b2 = 0.0
        return cls(W1, b1, W2, b2, input_dim=dim)

    # ---- forward ---------------------------------------------------------

    def _pre(self, x):
        """Return (a1, z): hidden tanh activations and the output logit."""
        W1, b1 = self.W1, self.b1
        a1 = [0.0] * self.hidden
        for j in range(self.hidden):
            row = W1[j]
            s = b1[j]
            for i, xi in enumerate(x):
                s += row[i] * xi
            a1[j] = math.tanh(s)
        z = self.b2
        W2 = self.W2
        for j in range(self.hidden):
            z += W2[j] * a1[j]
        return a1, z

    def forward(self, x) -> float:
        """Raw logit for the per-option input vector `x`."""
        return self._pre(x)[1]

    def logits(self, X) -> list:
        return [self._pre(x)[1] for x in X]

    def prior(self, X, temperature: float = 1.0) -> list:
        """Softmax prior over a selection's option inputs `X`."""
        return softmax(self.logits(X), temperature)

    # ---- training (stdlib softmax-CE SGD; torch path in train_policy.py) --

    def train_decision(self, X, pi, lr: float, l2: float = 0.0) -> float:
        """One SGD step on ONE decision: cross-entropy of softmax(logits(X)) vs
        the target visit distribution `pi`. Returns the decision's CE loss."""
        if not X:
            return 0.0
        pres = [self._pre(x) for x in X]
        p = softmax([z for _, z in pres])
        loss = -sum(pi[k] * math.log(max(p[k], 1e-12)) for k in range(len(X)))
        H, D = self.hidden, self.input_dim
        # dL/dz_k = p_k - pi_k (softmax + cross-entropy).
        gW1 = [[0.0] * D for _ in range(H)]
        gb1 = [0.0] * H
        gW2 = [0.0] * H
        gb2 = 0.0
        for k, (a1, _z) in enumerate(pres):
            g = p[k] - pi[k]
            gb2 += g
            x = X[k]
            for j in range(H):
                gW2[j] += g * a1[j]
                dz1 = g * self.W2[j] * (1.0 - a1[j] * a1[j])
                gb1[j] += dz1
                row = gW1[j]
                for i in range(D):
                    row[i] += dz1 * x[i]
        for j in range(H):
            w2 = self.W2[j]
            self.W2[j] = w2 - lr * (gW2[j] + l2 * w2)
            self.b1[j] -= lr * gb1[j]
            row, grow = self.W1[j], gW1[j]
            if l2:
                for i in range(D):
                    row[i] -= lr * (grow[i] + l2 * row[i])
            else:
                for i in range(D):
                    row[i] -= lr * grow[i]
        self.b2 -= lr * gb2
        return loss

    # ---- serialization ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "policy_feature_version": self.feature_version,
            "input_dim": self.input_dim,
            "hidden": self.hidden,
            "arch": [self.input_dim, self.hidden, 1],
            "activation": "tanh",
            "output": "linear",
            "W1": self.W1,
            "b1": self.b1,
            "W2": self.W2,
            "b2": self.b2,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PolicyNet":
        return cls(d["W1"], d["b1"], d["W2"], d["b2"],
                   input_dim=d.get("input_dim"),
                   feature_version=d.get("policy_feature_version"))

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str) -> "PolicyNet":
        with open(path) as f:
            return cls.from_dict(json.load(f))
