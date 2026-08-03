"""SOT-2334 — ELO-consistent gauntlet math (engine-independent).

Validates the core rating logic of eval/elo_gauntlet.py without touching the
slow cabt engine: the logistic ELO expectation, the order-free fixed-point
rating solver, and — the diagnostic's crux — that an *upset loss* (loss to a
lower-rated opponent) drains more rating than the matching upset *win* earns,
so a peer-parity champion can still net-leak rating on weak tiers.
"""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from eval.elo_gauntlet import (decompose, elo_expected, solve_rating,
                               DEFAULT_K)


class TestEloExpected(unittest.TestCase):
    def test_equal_rating_is_half(self):
        self.assertAlmostEqual(elo_expected(1500, 1500), 0.5)

    def test_favoured_vs_weak_is_high(self):
        # 400 points above -> ~0.909 expected score
        self.assertAlmostEqual(elo_expected(1500, 1100), 0.9090909, places=5)

    def test_monotone(self):
        self.assertGreater(elo_expected(1500, 1000), elo_expected(1500, 1400))


class TestFixedPointRating(unittest.TestCase):
    def test_balanced_field_recovers_anchor(self):
        # 50% vs a single peer anchor => R* == anchor.
        cells = [{"anchor": 1500.0, "wins": 50, "losses": 50, "draws": 0}]
        self.assertAlmostEqual(solve_rating(cells), 1500.0, places=1)

    def test_beats_weak_field_rates_above(self):
        # dominating a weak field => R* well above the weak anchor.
        cells = [{"anchor": 1200.0, "wins": 90, "losses": 10, "draws": 0}]
        self.assertGreater(solve_rating(cells), 1400.0)

    def test_order_free(self):
        # aggregate counts only -> deterministic regardless of match order.
        a = [{"anchor": 1300.0, "wins": 30, "losses": 20, "draws": 0},
             {"anchor": 1600.0, "wins": 15, "losses": 35, "draws": 0}]
        b = list(reversed(a))
        self.assertAlmostEqual(solve_rating(a), solve_rating(b), places=6)


class TestUpsetAsymmetry(unittest.TestCase):
    def test_upset_loss_costs_more_than_upset_win_earns(self):
        # champion at 1600, weak opponent at 1200 (expected ~0.909).
        r, opp = 1600.0, 1200.0
        e = elo_expected(r, opp)
        win_gain = DEFAULT_K * (1.0 - e)
        loss_drain = DEFAULT_K * (0.0 - e)
        self.assertGreater(abs(loss_drain), abs(win_gain))

    def test_peer_parity_but_weak_tier_net_negative(self):
        # The divergence crux, isolated at a fixed champion rating R*=1500
        # (== the peer anchor): a champion at 0.50 vs the peer is rating-
        # neutral there, yet at 0.70 win rate vs a much weaker tier it still
        # NET-DRAINS, because each upset loss costs K*E (E large) while each
        # win earns only K*(1-E). This is why win-rate ~0.5 (looks saturated)
        # and ELO leakage coexist.
        r_star = 1500.0
        cells = [
            {"cell": "peer", "tier": "peer", "anchor": 1500.0,
             "opp_agent": "mcts", "wins": 50, "losses": 50, "draws": 0,
             "loss_by_tag": {}},
            {"cell": "weak", "tier": "weak", "anchor": 1150.0,
             "opp_agent": "random", "wins": 70, "losses": 30, "draws": 0,
             "loss_by_tag": {"board_wipe": 28, "deck_out": 2}},
        ]
        dec = {d["cell"]: d for d in decompose(cells, r_star)}
        # peer ~ parity and ~ net-zero at R* == peer anchor
        self.assertAlmostEqual(dec["peer"]["winrate"], 0.5, places=6)
        self.assertAlmostEqual(dec["peer"]["net"], 0.0, places=6)
        # weak tier: >0.5 win rate yet NET-NEGATIVE (the divergence crux)
        self.assertGreater(dec["weak"]["winrate"], 0.5)
        self.assertLess(dec["weak"]["net"], 0.0)
        self.assertLess(dec["weak"]["net"], dec["peer"]["net"])
        self.assertTrue(dec["weak"]["is_upset_tier"])


if __name__ == "__main__":
    unittest.main()
