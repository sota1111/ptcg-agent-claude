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
                               _parse_eval_weights_override, DEFAULT_K,
                               build_field, compute_compare, ATTACK_LEVER,
                               classify_board_wipe, upset_board_wipe_breakdown,
                               _champ_snapshot, BOARD_WIPE_CAUSES,
                               OVERCOMMIT_ENERGY)


def _recs(seeds, cells):
    """Expand {cell: (wins, losses, tier, anchor)} into per-seed JSONL recs."""
    out = []
    for s in seeds:
        for cell, (w, l, tier, anchor) in cells.items():
            out.append({"seed": s, "cell": cell, "tier": tier,
                        "anchor": anchor, "opp_agent": "mcts",
                        "wins": w, "losses": l, "draws": 0, "loss_by_tag": {}})
    return out


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


class TestChampionEvalWeightsOverride(unittest.TestCase):
    """SOT-2335 — the champion-only eval_weights override parser that isolates
    a defence candidate against the fixed baseline opponent field."""

    def test_none_and_empty_are_no_override(self):
        self.assertIsNone(_parse_eval_weights_override(None))
        self.assertIsNone(_parse_eval_weights_override(""))

    def test_parses_json_object(self):
        got = _parse_eval_weights_override('{"bench_dev": 0.5, "bench_dev_cap": 2}')
        self.assertEqual(got, {"bench_dev": 0.5, "bench_dev_cap": 2})

    def test_rejects_non_object(self):
        with self.assertRaises(SystemExit):
            _parse_eval_weights_override("[1, 2]")

    def test_rejects_bad_json(self):
        with self.assertRaises(SystemExit):
            _parse_eval_weights_override("{not json}")


class TestEliteField(unittest.TestCase):
    def test_elite_cell_added_by_default(self):
        field = build_field(0.1)
        ids = [c["id"] for c in field]
        self.assertIn("mcts_elite", ids)
        elite = next(c for c in field if c["id"] == "mcts_elite")
        self.assertEqual(elite["tier"], "elite")
        # anchor above the peer mirror => a strong (rating-earning) tier
        peer = next(c for c in field if c["id"] == "mcts_peer")
        self.assertGreater(elite["anchor"], peer["anchor"])
        # deeper search than the champion budget
        self.assertGreater(elite["opp_config"]["time_budget_s"], 0.1)

    def test_no_elite_reproduces_sot2334_field(self):
        self.assertNotIn(
            "mcts_elite",
            [c["id"] for c in build_field(0.1, include_elite=False)])


class TestAttackLeverCompare(unittest.TestCase):
    def _base(self):
        # champion ~parity peer, loses some to elite/strong, clean weak tiers
        return {
            "random": (18, 2, "weak", 1000.0),
            "rule": (14, 6, "weak", 1230.0),
            "greedy": (13, 7, "mid", 1330.0),
            "mcts_peer": (10, 10, "peer", 1560.0),
            "mcts_high": (7, 13, "strong", 1660.0),
            "mcts_elite": (5, 15, "elite", 1760.0),
        }

    def test_promote_when_strong_up_and_weak_held(self):
        base = _recs([1, 2, 3], self._base())
        var_cells = dict(self._base())
        # lever converts strong/elite upset wins, weak tiers unchanged
        var_cells["mcts_high"] = (12, 8, "strong", 1660.0)
        var_cells["mcts_elite"] = (10, 10, "elite", 1760.0)
        var = _recs([1, 2, 3], var_cells)
        res = compute_compare(base, var)
        self.assertGreater(res["r_star_gain"], 0)
        self.assertTrue(res["all_seeds_up"])
        self.assertTrue(res["no_regression"])
        self.assertEqual(res["verdict"], "PROMOTE")

    def test_non_promote_when_weak_tier_regresses(self):
        base = _recs([1, 2, 3], self._base())
        var_cells = dict(self._base())
        # small strong-tier gain but the lever bleeds NEW weak-tier upsets
        var_cells["mcts_high"] = (9, 11, "strong", 1660.0)
        var_cells["rule"] = (7, 13, "weak", 1230.0)
        var_cells["greedy"] = (7, 13, "mid", 1330.0)
        var = _recs([1, 2, 3], var_cells)
        res = compute_compare(base, var)
        self.assertFalse(res["no_regression"])
        self.assertEqual(res["verdict"], "NON-PROMOTE")

    def test_non_promote_when_flat(self):
        base = _recs([1, 2, 3], self._base())
        var = _recs([1, 2, 3], self._base())
        res = compute_compare(base, var)
        self.assertEqual(res["verdict"], "NON-PROMOTE")

    def test_attack_lever_lowers_deviate_margin(self):
        # the lever is a decision-commitment diff, not compute/eval
        self.assertIn("deviate_margin", ATTACK_LEVER)
        self.assertLess(ATTACK_LEVER["deviate_margin"], 0.1)


class TestClassifyBoardWipe(unittest.TestCase):
    """SOT-2365 — board_wipe decision-cause attribution from the champion's
    last pre-terminal board snapshot (diagnostic-only, intentionally coarse)."""

    def test_overcommit_from_energy(self):
        # >= OVERCOMMIT_ENERGY energies on the doomed Active -> over-commitment,
        # even with a non-empty bench.
        self.assertEqual(classify_board_wipe(0, OVERCOMMIT_ENERGY, False),
                         "doomed_active_overcommit")
        self.assertEqual(classify_board_wipe(2, 3, False),
                         "doomed_active_overcommit")

    def test_overcommit_from_evolution(self):
        # an evolved Active is a resource commitment even with 1 energy
        self.assertEqual(classify_board_wipe(0, 1, True),
                         "doomed_active_overcommit")

    def test_unpromotable_empty_bench_no_investment(self):
        # empty bench + no over-commit signal -> survival-bench shortfall
        self.assertEqual(classify_board_wipe(0, 1, False), "unpromotable")
        self.assertEqual(classify_board_wipe(0, None, None), "unpromotable")

    def test_other_when_not_clearly_determinable(self):
        # non-empty bench but light Active investment -> residual bucket
        self.assertEqual(classify_board_wipe(2, 1, False), "other_wipe")
        # champion side never resolved (all None) -> residual, never over-claim
        self.assertEqual(classify_board_wipe(None, None, None), "other_wipe")

    def test_causes_are_the_declared_partition(self):
        for args in [(0, 2, False), (0, 1, False), (2, 1, False),
                     (None, None, None)]:
            self.assertIn(classify_board_wipe(*args), BOARD_WIPE_CAUSES)


class TestChampSnapshot(unittest.TestCase):
    """SOT-2365 — champion-side board snapshot reads the ABSOLUTE seat and is
    defensive against missing/odd keys."""

    def _obs(self, seat0, seat1):
        return {"current": {"players": [seat0, seat1]}}

    def test_reads_absolute_seat_and_active_energy(self):
        champ = {"bench": [{"id": 1}, {"id": 2}],
                 "active": [{"id": 9, "energies": [0, 1, 2],
                             "preEvolution": [{"id": 5}]}]}
        opp = {"bench": [], "active": [{"id": 7}]}
        # champion at seat 1 -> resolve seat 1 regardless of the opponent side
        bench, energy, evolved = _champ_snapshot(self._obs(opp, champ), 1)
        self.assertEqual(bench, 2)
        self.assertEqual(energy, 3)
        self.assertTrue(evolved)

    def test_no_active_returns_none_energy(self):
        side = {"bench": [{"id": 1}], "active": []}
        bench, energy, evolved = _champ_snapshot(self._obs(side, {}), 0)
        self.assertEqual(bench, 1)
        self.assertIsNone(energy)
        self.assertIsNone(evolved)

    def test_unresolvable_side_returns_none(self):
        self.assertIsNone(_champ_snapshot({"current": {"players": []}}, 0))
        self.assertIsNone(_champ_snapshot({}, 0))

    def test_missing_keys_do_not_raise(self):
        # empty side dict -> bench 0, no active
        self.assertEqual(_champ_snapshot(self._obs({}, {}), 0), (0, None, None))


class TestUpsetBoardWipeNet(unittest.TestCase):
    """SOT-2365 — the downstream children's target metric aggregates board_wipe
    drain + causes over the UPSET tiers only."""

    def _cells(self):
        return [
            # upset tier (anchor < R*=1500): 25 board_wipe losses, 3 causes
            {"cell": "weak", "tier": "weak", "anchor": 1150.0,
             "opp_agent": "random", "wins": 70, "losses": 30, "draws": 0,
             "loss_by_tag": {"board_wipe": 25, "deck_out": 5},
             "board_wipe_by_cause": {"unpromotable": 15,
                                     "doomed_active_overcommit": 8,
                                     "other_wipe": 2}},
            # NON-upset strong tier (anchor 1660 > R*): excluded from the metric
            {"cell": "strong", "tier": "strong", "anchor": 1660.0,
             "opp_agent": "mcts", "wins": 30, "losses": 70, "draws": 0,
             "loss_by_tag": {"board_wipe": 40},
             "board_wipe_by_cause": {"unpromotable": 40}},
        ]

    def test_breakdown_over_upset_tiers_only(self):
        r_star = 1500.0
        dec = decompose(self._cells(), r_star)
        br = upset_board_wipe_breakdown(dec)
        # only the weak (upset) tier contributes; strong (non-upset) excluded
        self.assertEqual(br["by_cause"], {"unpromotable": 15,
                                          "doomed_active_overcommit": 8,
                                          "other_wipe": 2})
        self.assertEqual(br["losses"], 25)
        # net = board_wipe_losses * K*(0-E@R*), strictly negative (a drain)
        e = elo_expected(r_star, 1150.0)
        self.assertAlmostEqual(br["net"], 25 * DEFAULT_K * (0.0 - e), places=6)
        self.assertLess(br["net"], 0)

    def test_cause_counts_partition_board_wipe_count(self):
        # regression invariant: the upset causes sum to the upset board_wipe
        # loss count (each board_wipe loss has exactly one cause)
        dec = decompose(self._cells(), 1500.0)
        br = upset_board_wipe_breakdown(dec)
        self.assertEqual(sum(br["by_cause"].values()), br["losses"])

    def test_empty_and_legacy_records_are_safe(self):
        # cells with no board_wipe_by_cause (pre-2365 JSONL) -> empty breakdown
        cells = [{"cell": "weak", "tier": "weak", "anchor": 1150.0,
                  "opp_agent": "random", "wins": 5, "losses": 5, "draws": 0,
                  "loss_by_tag": {}}]
        br = upset_board_wipe_breakdown(decompose(cells, 1500.0))
        self.assertEqual(br["losses"], 0)
        self.assertEqual(br["by_cause"], {})
        self.assertEqual(br["net"], 0.0)


if __name__ == "__main__":
    unittest.main()
