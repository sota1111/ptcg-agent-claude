"""PolicyNet / policy features (SOT-1916) — engine-free unit tests.

Pins the pure-Python policy-prior forward pass, the export/reload consistency
(the SOT-1837 "一致テスト" carried to the policy head), the feature-layout
dimensions, and the POLICY_FEATURE_VERSION load guard. The behavioural A/B lives
in docs/expert_iteration (bench screen); these tests fix the contract the
trainer and the inference prior share.
"""
import json
import os
import random
import tempfile
import unittest

from agents.policy_features import (OPTION_BLOCK_DIM, OPTION_TYPE_COUNT,
                                    POLICY_FEATURE_VERSION, POLICY_INPUT_DIM,
                                    STATE_DIM)
from agents.policy_net import PolicyNet, softmax


class TestPolicyFeatures(unittest.TestCase):
    def test_dimensions_are_consistent(self):
        self.assertEqual(POLICY_INPUT_DIM, STATE_DIM + OPTION_BLOCK_DIM)
        self.assertGreater(OPTION_BLOCK_DIM, OPTION_TYPE_COUNT + 1)

    def test_softmax_normalizes(self):
        p = softmax([1.0, 2.0, 3.0])
        self.assertAlmostEqual(sum(p), 1.0, places=9)
        self.assertTrue(all(0.0 <= x <= 1.0 for x in p))
        self.assertEqual(softmax([]), [])

    def test_softmax_temperature_flattens(self):
        sharp = softmax([0.0, 5.0], temperature=0.5)
        flat = softmax([0.0, 5.0], temperature=50.0)
        self.assertGreater(sharp[1], flat[1])  # colder => more peaked


class TestPolicyNet(unittest.TestCase):
    def _net(self):
        rng = random.Random(1916)
        return PolicyNet.init(hidden=8, rng=rng, dim=POLICY_INPUT_DIM)

    def test_forward_is_finite_logit(self):
        net = self._net()
        x = [0.1] * POLICY_INPUT_DIM
        z = net.forward(x)
        self.assertIsInstance(z, float)

    def test_save_load_roundtrip_is_exact(self):
        net = self._net()
        xs = [[random.Random(i).uniform(-1, 1) for _ in range(POLICY_INPUT_DIM)]
              for i in range(20)]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "policy.json")
            net.save(p)
            reloaded = PolicyNet.load(p)
            for x in xs:
                self.assertAlmostEqual(net.forward(x), reloaded.forward(x),
                                       places=12)
            with open(p) as f:
                blob = json.load(f)
            self.assertEqual(blob["policy_feature_version"],
                             POLICY_FEATURE_VERSION)
            self.assertEqual(blob["input_dim"], POLICY_INPUT_DIM)
            self.assertEqual(blob["output"], "linear")

    def test_train_decision_reduces_ce_on_a_fixed_target(self):
        net = self._net()
        X = [[random.Random(k).uniform(-1, 1) for _ in range(POLICY_INPUT_DIM)]
             for k in range(4)]
        pi = [0.7, 0.2, 0.1, 0.0]
        before = net.train_decision(X, pi, lr=0.0)  # loss only (lr 0 = no step)
        for _ in range(200):
            net.train_decision(X, pi, lr=0.1)
        after = -sum(pi[k] * __import__("math").log(max(
            softmax(net.logits(X))[k], 1e-12)) for k in range(4))
        self.assertLess(after, before)


class TestLearnedPriorGuard(unittest.TestCase):
    def test_feature_version_mismatch_raises(self):
        from agents.learned_prior import LearnedPrior
        net = PolicyNet.init(4, random.Random(0), dim=POLICY_INPUT_DIM)
        net.feature_version = POLICY_FEATURE_VERSION + 99
        with self.assertRaises(ValueError):
            LearnedPrior(net, card_index=object())


if __name__ == "__main__":
    unittest.main()
