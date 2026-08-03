"""SOT-2367 — conditional survival-bench boost (board-wipe resilience at the
action-prior layer, gated on an imminent wipe). Opt-in: all three knobs
off => champion behaviour unchanged. Distinct from SOT-1941's UNCONDITIONAL
early_bench (this fires only when the Active is near-KO / absent AND the bench
is below the survival floor). Engine-independent."""
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from agents.greedy_agent import GreedyAgent
from agents.observation import adapt
from agents.planner import MctsPlanner, PlannerConfig
from tests.support import (card, observation, player, pokemon, select,
                           synthetic_card_index)

# card 101 = Basic Pokémon (max HP 120 in the synthetic master).
_OT_PLAY = 7


def view_play_basic(active=None, bench=()):
    """A MAIN selection whose only option is PLAY hand[0] (a basic Pokémon),
    with a configurable own Active (None => no active) and bench."""
    active_arg = () if active is None else (active,)
    me = player(active=active_arg, bench=list(bench), hand=[card(101)])
    sel = select([{"type": _OT_PLAY, "index": 0}], context=0,
                 min_count=1, max_count=1)
    return adapt(observation(sel, me=me))


def play_score(agent, view):
    return agent.score_options(view)[0]


class TestSurvivalBenchBoost(unittest.TestCase):
    def setUp(self):
        self.idx = synthetic_card_index()
        # frac 0.5 => "near-KO" means current HP at or below half of max.
        self.boosted = GreedyAgent(
            seed=0, card_index=self.idx, survival_bench_boost=20.0,
            survival_bench_floor=2, survival_hp_frac=0.5)
        self.base = GreedyAgent(seed=0, card_index=self.idx)

    def test_default_is_champion(self):
        off = GreedyAgent(seed=0, card_index=self.idx,
                          survival_bench_boost=0.0, survival_bench_floor=0,
                          survival_hp_frac=0.0)
        v = view_play_basic(active=pokemon(101, hp=10, max_hp=120), bench=())
        self.assertEqual(play_score(self.base, v), play_score(off, v))

    def test_no_boost_when_active_healthy(self):
        # Active at full HP => no wipe threat => no boost even on an empty bench.
        healthy = view_play_basic(active=pokemon(101, hp=120, max_hp=120),
                                  bench=())
        self.assertEqual(play_score(self.boosted, healthy),
                         play_score(self.base, healthy))

    def test_boost_when_active_near_ko(self):
        # Active at 30/120 (<= 0.5 frac) and empty bench (deficit 2) => boost.
        risky = view_play_basic(active=pokemon(101, hp=30, max_hp=120),
                                bench=())
        self.assertAlmostEqual(play_score(self.boosted, risky),
                               play_score(self.base, risky) + 20.0 * 2)

    def test_boost_when_no_active(self):
        # No Active at all (just KO'd / not yet established) => at risk.
        empty = view_play_basic(active=None, bench=())
        self.assertAlmostEqual(play_score(self.boosted, empty),
                               play_score(self.base, empty) + 20.0 * 2)

    def test_hp_fraction_threshold_is_inclusive_boundary(self):
        # Exactly at the frac (60/120 == 0.5) counts as near-KO.
        at = view_play_basic(active=pokemon(101, hp=60, max_hp=120), bench=())
        self.assertAlmostEqual(play_score(self.boosted, at),
                               play_score(self.base, at) + 20.0 * 2)
        # Just above (61/120) is safe => no boost.
        above = view_play_basic(active=pokemon(101, hp=61, max_hp=120),
                                bench=())
        self.assertEqual(play_score(self.boosted, above),
                         play_score(self.base, above))

    def test_boost_saturates_at_floor(self):
        # Bench already at the survival floor => no boost, even when near-KO.
        full = view_play_basic(active=pokemon(101, hp=10, max_hp=120),
                               bench=(pokemon(101), pokemon(101)))
        self.assertEqual(play_score(self.boosted, full),
                         play_score(self.base, full))
        # Partial bench (1 of 2) with a near-KO active still earns the deficit.
        partial = view_play_basic(active=pokemon(101, hp=10, max_hp=120),
                                  bench=(pokemon(101),))
        self.assertAlmostEqual(play_score(self.boosted, partial),
                               play_score(self.base, partial) + 20.0 * 1)

    def test_independent_of_early_bench(self):
        # The two levers stack additively and each stays off by default.
        both = GreedyAgent(seed=0, card_index=self.idx,
                           bench_boost=5.0, bench_floor=3,
                           survival_bench_boost=20.0, survival_bench_floor=2,
                           survival_hp_frac=0.5)
        risky = view_play_basic(active=pokemon(101, hp=10, max_hp=120),
                                bench=())
        # early_bench: 5*3 (deficit 3); survival: 20*2 (deficit 2, near-KO).
        self.assertAlmostEqual(play_score(both, risky),
                               play_score(self.base, risky) + 5.0 * 3 + 20.0 * 2)

    def test_planner_config_defaults_off(self):
        cfg = PlannerConfig()
        self.assertEqual(cfg.survival_bench, 0.0)
        self.assertEqual(cfg.survival_bench_floor, 0)
        self.assertEqual(cfg.survival_hp_frac, 0.0)
        planner = MctsPlanner(own_deck=[101] * 60, config=cfg,
                              card_index=self.idx)
        self.assertEqual(planner._greedy._survival_bench_boost, 0.0)
        self.assertEqual(planner._greedy._survival_bench_floor, 0)
        self.assertEqual(planner._greedy._survival_hp_frac, 0.0)

    def test_planner_config_threads_into_greedy(self):
        cfg = PlannerConfig(survival_bench=0.4, survival_bench_floor=2,
                            survival_hp_frac=0.5)
        planner = MctsPlanner(own_deck=[101] * 60, config=cfg,
                              card_index=self.idx)
        self.assertEqual(planner._greedy._survival_bench_boost, 0.4)
        self.assertEqual(planner._greedy._survival_bench_floor, 2)
        self.assertEqual(planner._greedy._survival_hp_frac, 0.5)


if __name__ == "__main__":
    unittest.main()
