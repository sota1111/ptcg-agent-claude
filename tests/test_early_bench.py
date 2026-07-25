"""SOT-1941 — early-bench development boost (board-wipe resilience at the
action-prior layer). Opt-in: both knobs 0 => champion behaviour unchanged.
Engine-independent."""
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

# card 101 = Basic Water Pokémon; 103 = Supporter (both in the synthetic master)
_OT_PLAY = 7


def view_play_basic(bench=()):
    """A MAIN selection whose only option is PLAY hand[0] (a basic Pokémon)."""
    me = player(active=(pokemon(101),), bench=list(bench), hand=[card(101)])
    sel = select([{"type": _OT_PLAY, "index": 0}], context=0,
                 min_count=1, max_count=1)
    return adapt(observation(sel, me=me))


def play_score(agent, view):
    return agent.score_options(view)[0]


class TestEarlyBenchBoost(unittest.TestCase):
    def setUp(self):
        self.idx = synthetic_card_index()

    def test_default_is_champion(self):
        # Both knobs default to 0 => a basic-Pokémon play scores identically
        # whether the boost fields are omitted or explicitly zero.
        base = GreedyAgent(seed=0, card_index=self.idx)
        off = GreedyAgent(seed=0, card_index=self.idx,
                          bench_boost=0.0, bench_floor=0)
        v = view_play_basic(bench=())
        self.assertEqual(play_score(base, v), play_score(off, v))

    def test_boost_raises_play_priority_on_thin_bench(self):
        base = GreedyAgent(seed=0, card_index=self.idx)
        boosted = GreedyAgent(seed=0, card_index=self.idx,
                              bench_boost=20.0, bench_floor=3)
        v = view_play_basic(bench=())  # 0 bench, deficit = 3
        self.assertAlmostEqual(play_score(boosted, v),
                               play_score(base, v) + 20.0 * 3)

    def test_boost_saturates_at_floor(self):
        # A bench already at/above the floor earns no boost (front-loaded).
        base = GreedyAgent(seed=0, card_index=self.idx)
        boosted = GreedyAgent(seed=0, card_index=self.idx,
                              bench_boost=20.0, bench_floor=3)
        full = view_play_basic(bench=(pokemon(101), pokemon(101), pokemon(101)))
        self.assertEqual(play_score(boosted, full), play_score(base, full))
        # Partial bench (1 of 3) still earns the remaining deficit.
        partial = view_play_basic(bench=(pokemon(101),))
        self.assertAlmostEqual(play_score(boosted, partial),
                               play_score(base, partial) + 20.0 * 2)

    def test_planner_config_defaults_off(self):
        # Champion PlannerConfig leaves the boost disabled; the planner's
        # shared greedy therefore carries a zero boost.
        cfg = PlannerConfig()
        self.assertEqual(cfg.early_bench, 0.0)
        self.assertEqual(cfg.early_bench_floor, 0)
        planner = MctsPlanner(own_deck=[101] * 60, config=cfg,
                              card_index=self.idx)
        self.assertEqual(planner._greedy._bench_boost, 0.0)
        self.assertEqual(planner._greedy._bench_floor, 0)

    def test_planner_config_threads_boost_into_greedy(self):
        cfg = PlannerConfig(early_bench=0.3, early_bench_floor=2)
        planner = MctsPlanner(own_deck=[101] * 60, config=cfg, card_index=self.idx)
        self.assertEqual(planner._greedy._bench_boost, 0.3)
        self.assertEqual(planner._greedy._bench_floor, 2)


if __name__ == "__main__":
    unittest.main()
