"""SOT-2366 — wipe-risk conservative retreat / anti-overcommit search
behaviour. Opt-in: both biases 0 => champion behaviour byte-identical. When the
root player's Active is DOOMED (near-KO AND the opponent can KO it next turn),
the lever raises the retreat option priority (only if a survivable bench target
exists) and lowers attach-to-active / evolve-of-active priority. Targets the
SOT-2365 `doomed_active_overcommit` board_wipe cause. Engine-independent."""
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

# Synthetic master (tests/support): 101 = Basic Water, attack 50, no weakness;
# 102 = Basic Fire (max HP 60), WEAK to Water(3). So a 101 Active attacking a
# 102 Active deals 50*2 = 100 (an easy KO) — a stable, HP-frac-governed threat.
_OT_ATTACH = 8
_OT_EVOLVE = 9
_OT_RETREAT = 12
_AREA_ACTIVE = 4
_AREA_BENCH = 5


def build_view(option, active, opp_active=None, bench=()):
    """Single-option MAIN selection with a configurable own Active / bench and
    opponent Active, from the acting player's perspective."""
    active_arg = () if active is None else (active,)
    opp_arg = () if opp_active is None else (opp_active,)
    me = player(active=active_arg, bench=list(bench), hand=[card(101)])
    opp = player(active=opp_arg, hand=None)
    sel = select([option], context=0, min_count=1, max_count=1)
    return adapt(observation(sel, me=me, opp=opp))


def score0(agent, view):
    return agent.score_options(view)[0]


# --- reusable options / boards ------------------------------------------------
RETREAT = {"type": _OT_RETREAT}
ATTACH_ACTIVE = {"type": _OT_ATTACH, "inPlayArea": _AREA_ACTIVE}
ATTACH_BENCH = {"type": _OT_ATTACH, "inPlayArea": _AREA_BENCH}
EVOLVE_ACTIVE = {"type": _OT_EVOLVE, "area": _AREA_ACTIVE, "index": 0,
                 "playerIndex": 0}
EVOLVE_BENCH = {"type": _OT_EVOLVE, "area": _AREA_BENCH, "index": 0,
                "playerIndex": 0}

# A doomed Active: 102 at 20/60 (<=0.5 frac) facing a 101 that hits it for 100.
DOOMED = dict(active=pokemon(102, hp=20, max_hp=60),
              opp_active=pokemon(101))
SURVIVABLE_BENCH = (pokemon(101, hp=120, max_hp=120),)  # healthy promotion


class TestWipeRetreat(unittest.TestCase):
    def setUp(self):
        self.idx = synthetic_card_index()
        self.lever = GreedyAgent(
            seed=0, card_index=self.idx, wipe_retreat_bias=30.0,
            wipe_overcommit_penalty=25.0, active_vulnerable_hp_frac=0.5)
        self.base = GreedyAgent(seed=0, card_index=self.idx)

    # ---- byte-identical default ------------------------------------------
    def test_default_is_champion(self):
        off = GreedyAgent(seed=0, card_index=self.idx, wipe_retreat_bias=0.0,
                          wipe_overcommit_penalty=0.0,
                          active_vulnerable_hp_frac=0.0)
        for opt in (RETREAT, ATTACH_ACTIVE, EVOLVE_ACTIVE):
            v = build_view(opt, bench=SURVIVABLE_BENCH, **DOOMED)
            self.assertEqual(score0(off, v), score0(self.base, v))

    # ---- retreat preference ----------------------------------------------
    def test_retreat_boost_when_doomed(self):
        v = build_view(RETREAT, bench=SURVIVABLE_BENCH, **DOOMED)
        self.assertAlmostEqual(score0(self.lever, v),
                               score0(self.base, v) + 30.0)

    def test_no_retreat_boost_when_active_healthy(self):
        # 50/60 (>0.5) => not near-KO even though the opponent could KO it.
        v = build_view(RETREAT, active=pokemon(102, hp=50, max_hp=60),
                       opp_active=pokemon(101), bench=SURVIVABLE_BENCH)
        self.assertEqual(score0(self.lever, v), score0(self.base, v))

    def test_no_retreat_boost_when_no_incoming_ko(self):
        # 101 Active (no weakness) at 45/120 (<=0.5) but the opponent 102 hits
        # for only 30 (<45) => not doomed => no boost.
        v = build_view(RETREAT, active=pokemon(101, hp=45, max_hp=120),
                       opp_active=pokemon(102), bench=SURVIVABLE_BENCH)
        self.assertEqual(score0(self.lever, v), score0(self.base, v))

    def test_no_retreat_boost_without_opponent_active(self):
        v = build_view(RETREAT, bench=SURVIVABLE_BENCH,
                       active=pokemon(102, hp=20, max_hp=60), opp_active=None)
        self.assertEqual(score0(self.lever, v), score0(self.base, v))

    def test_no_retreat_boost_without_survivable_target(self):
        # Bench pokemon is itself near-KO (20/120 <= 0.5) => promoting it just
        # moves the doom, so no retreat boost.
        doomed_bench = (pokemon(101, hp=20, max_hp=120),)
        v = build_view(RETREAT, bench=doomed_bench, **DOOMED)
        self.assertEqual(score0(self.lever, v), score0(self.base, v))
        # Empty bench => no target => no boost.
        v2 = build_view(RETREAT, bench=(), **DOOMED)
        self.assertEqual(score0(self.lever, v2), score0(self.base, v2))

    def test_hp_fraction_threshold_is_inclusive(self):
        at = build_view(RETREAT, active=pokemon(102, hp=30, max_hp=60),
                        opp_active=pokemon(101), bench=SURVIVABLE_BENCH)
        self.assertAlmostEqual(score0(self.lever, at),
                               score0(self.base, at) + 30.0)
        above = build_view(RETREAT, active=pokemon(102, hp=31, max_hp=60),
                           opp_active=pokemon(101), bench=SURVIVABLE_BENCH)
        self.assertEqual(score0(self.lever, above), score0(self.base, above))

    # ---- anti-overcommit --------------------------------------------------
    def test_penalty_attach_to_doomed_active(self):
        v = build_view(ATTACH_ACTIVE, bench=SURVIVABLE_BENCH, **DOOMED)
        self.assertAlmostEqual(score0(self.lever, v),
                               score0(self.base, v) - 25.0)

    def test_no_penalty_attach_to_bench(self):
        v = build_view(ATTACH_BENCH, bench=SURVIVABLE_BENCH, **DOOMED)
        self.assertEqual(score0(self.lever, v), score0(self.base, v))

    def test_penalty_evolve_doomed_active(self):
        v = build_view(EVOLVE_ACTIVE, bench=SURVIVABLE_BENCH, **DOOMED)
        self.assertAlmostEqual(score0(self.lever, v),
                               score0(self.base, v) - 25.0)

    def test_no_penalty_evolve_bench(self):
        v = build_view(EVOLVE_BENCH, bench=SURVIVABLE_BENCH, **DOOMED)
        self.assertEqual(score0(self.lever, v), score0(self.base, v))

    def test_no_penalty_when_active_not_doomed(self):
        # Healthy Active => attach-to-active keeps its champion score.
        v = build_view(ATTACH_ACTIVE, active=pokemon(102, hp=50, max_hp=60),
                       opp_active=pokemon(101), bench=SURVIVABLE_BENCH)
        self.assertEqual(score0(self.lever, v), score0(self.base, v))

    def test_retreat_and_overcommit_are_independent(self):
        # retreat_bias only (no penalty): attach unchanged, retreat boosted.
        retreat_only = GreedyAgent(seed=0, card_index=self.idx,
                                   wipe_retreat_bias=30.0,
                                   active_vulnerable_hp_frac=0.5)
        rv = build_view(RETREAT, bench=SURVIVABLE_BENCH, **DOOMED)
        av = build_view(ATTACH_ACTIVE, bench=SURVIVABLE_BENCH, **DOOMED)
        self.assertAlmostEqual(score0(retreat_only, rv),
                               score0(self.base, rv) + 30.0)
        self.assertEqual(score0(retreat_only, av), score0(self.base, av))

    # ---- PlannerConfig plumbing ------------------------------------------
    def test_planner_config_defaults_off(self):
        cfg = PlannerConfig()
        self.assertEqual(cfg.wipe_retreat_bias, 0.0)
        self.assertEqual(cfg.wipe_overcommit_penalty, 0.0)
        self.assertEqual(cfg.active_vulnerable_hp_frac, 0.0)
        planner = MctsPlanner(own_deck=[101] * 60, config=cfg,
                              card_index=self.idx)
        self.assertEqual(planner._greedy._wipe_retreat_bias, 0.0)
        self.assertEqual(planner._greedy._wipe_overcommit_penalty, 0.0)
        self.assertEqual(planner._greedy._active_vulnerable_hp_frac, 0.0)

    def test_planner_config_threads_into_greedy(self):
        cfg = PlannerConfig(wipe_retreat_bias=30.0, wipe_overcommit_penalty=25.0,
                            active_vulnerable_hp_frac=0.5)
        planner = MctsPlanner(own_deck=[101] * 60, config=cfg,
                              card_index=self.idx)
        self.assertEqual(planner._greedy._wipe_retreat_bias, 30.0)
        self.assertEqual(planner._greedy._wipe_overcommit_penalty, 25.0)
        self.assertEqual(planner._greedy._active_vulnerable_hp_frac, 0.5)


if __name__ == "__main__":
    unittest.main()
