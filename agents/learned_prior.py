"""Learned action-prior (SOT-1916) — optional policy-prior drop-in.

`LearnedPrior.prior_scores(view, greedy_scores)` returns a per-option score that
REPLACES the greedy prior the MCTS planner ranks/softmaxes at the root
(agents/planner.py:_root_candidates). Opt-in only: the champion never
constructs one (main.py FABLE_CONFIG has no `learned_prior`); it is built solely
when a bench/A-B config or the `FABLE_LEARNED_PRIOR` env var asks for it.

The forward pass and feature layout are the pure-Python, numpy-free modules
shared with the trainer (`agents.policy_net` / `agents.policy_features`), so the
weights a GPU run produces reload unchanged into the Kaggle submission path.
POLICY_FEATURE_VERSION mismatch raises at load time rather than mispredicting.
"""
from .cards import shared_index
from .policy_features import (POLICY_FEATURE_VERSION, extract, option_feature,
                              option_input)
from .policy_net import PolicyNet


class LearnedPrior:
    """Per-option policy scorer over the engine's legal options."""

    def __init__(self, net: PolicyNet, card_index=None):
        if net.feature_version != POLICY_FEATURE_VERSION:
            raise ValueError(
                f"policy net feature_version {net.feature_version} != "
                f"runtime {POLICY_FEATURE_VERSION}; retrain/export before use")
        self.net = net
        self._cards = card_index if card_index is not None else shared_index()

    @classmethod
    def from_path(cls, path: str, card_index=None) -> "LearnedPrior":
        return cls(PolicyNet.load(path), card_index=card_index)

    def prior_scores(self, view, greedy_scores) -> list:
        """Per-option learned logits for `view.select` (same length/order as
        `view.select.options`). `greedy_scores` is that selection's GreedyAgent
        score list — passed in so the learned correction sees the EXACT scores
        the planner would otherwise have used (no recompute, no drift)."""
        sel = view.select
        state = extract(view.raw, view.your_index)
        opts = sel.options
        X = [option_input(state,
                          option_feature(view, opts[i], greedy_scores[i],
                                         self._cards))
             for i in range(len(opts))]
        return self.net.logits(X)
