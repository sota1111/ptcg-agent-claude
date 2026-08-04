"""SOT-2403 — Single-Observer ISMCTS (single shared information-set tree).

Opt-in: `PlannerConfig.ismcts` default OFF => the determinized MCTS path is
byte-identical to the champion (main.py untouched). ON => one shared tree fed
by the champion's `n_worlds` determinization pool, with a legal-action filter
and availability-corrected UCB replacing the per-world averaged aggregation
(the strategy-fusion mitigation). Engine-independent: the search API is stubbed
by a deterministic backend double, mirroring tests/test_mcts.py.
"""
import math
import os
import sys
import unittest
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from agents.observation import adapt
from agents.planner import MctsPlanner, PlannerConfig, _ISNode
from agents.rng import Rng
from tests.support import (observation, player, pokemon, select,
                           synthetic_card_index)


def main_view(n_options=3):
    opts = [{"type": 13, "attackId": 201 + i, "number": 0} for i in
            range(n_options)]
    return adapt(observation(
        select(opts, sel_type=0, context=0, min_count=1, max_count=1),
        me=player(active=[pokemon(101, energies=[3])]),
        opp=player(active=[pokemon(102)])))


class _ScriptedBackend:
    """Deterministic engine double: stepping action [1] wins for player 0, any
    other root action loses. Tracks live search states so a leak is detectable
    (every begun/forked sid must be released)."""

    def __init__(self):
        self.next_sid = 0
        self.begins = 0
        self.live = set()

    def begin(self, raw_obs, fills, manual_coin=True):
        self.next_sid += 1
        self.begins += 1
        self.live.add(self.next_sid)
        sel = SimpleNamespace(option=[SimpleNamespace(type=13, number=0)] * 3,
                              minCount=1, maxCount=1, context=0)
        obs = SimpleNamespace(
            select=sel,
            current=SimpleNamespace(result=-1, yourIndex=0, turn=1))
        return self.next_sid, obs

    def step(self, sid, action):
        self.next_sid += 1
        self.live.add(self.next_sid)
        result = 0 if action == [1] else 1
        obs = SimpleNamespace(
            select=None,
            current=SimpleNamespace(result=result, yourIndex=0, turn=1))
        return self.next_sid, obs

    def release(self, sid):
        self.live.discard(sid)

    def end(self):
        pass


class _ExplodingBackend:
    calls = 0

    def begin(self, raw_obs, fills, manual_coin=True):
        self.calls += 1
        raise RuntimeError("no engine")

    def end(self):
        pass


def _planner(backend, **overrides):
    overrides.setdefault("ismcts", True)
    return MctsPlanner(own_deck=[101] * 60,
                       config=PlannerConfig(**overrides),
                       backend=backend, card_index=synthetic_card_index())


class TestIsmctsDefaultOff(unittest.TestCase):
    def test_flag_defaults_off(self):
        self.assertFalse(PlannerConfig().ismcts)

    def test_default_is_champion_path(self):
        # ismcts=False must take the determinized path (last_stats carries no
        # ismcts marker) and match the champion planner byte-for-byte on the
        # scripted backend.
        champ = _planner(_ScriptedBackend(), ismcts=False, n_worlds=3,
                         max_iterations=24, time_budget_s=30.0,
                         max_root_actions=3)
        a = champ.plan(main_view(3), Rng(7))
        self.assertNotIn("ismcts", champ.last_stats)
        self.assertEqual(a, [1])  # scripted win still found by the champion


class TestActionKeys(unittest.TestCase):
    def test_opt_key_excludes_serial(self):
        # Same semantic option, different engine-assigned instance serial (a
        # per-determinization id for hidden cards) => SAME shared-tree key.
        o1 = SimpleNamespace(type=7, cardId=103, index=0, serial=5001)
        o2 = SimpleNamespace(type=7, cardId=103, index=0, serial=9999)
        self.assertEqual(MctsPlanner._opt_key(o1), MctsPlanner._opt_key(o2))

    def test_opt_key_distinguishes_semantics(self):
        o1 = SimpleNamespace(type=7, cardId=103, index=0)
        o2 = SimpleNamespace(type=7, cardId=104, index=0)  # different card
        self.assertNotEqual(MctsPlanner._opt_key(o1), MctsPlanner._opt_key(o2))

    def test_action_key_multiselect_order_independent(self):
        p = _planner(None)
        obs = SimpleNamespace(select=SimpleNamespace(option=[
            SimpleNamespace(type=8, cardId=201, area=None),
            SimpleNamespace(type=8, cardId=202, area=None)]))
        # Same pair of options, different index order => same canonical key.
        self.assertEqual(p._action_key(obs, [0, 1]), p._action_key(obs, [1, 0]))


class TestIsmctsSelection(unittest.TestCase):
    def test_untried_expands_highest_prior(self):
        p = _planner(None)
        node = _ISNode()  # nothing visited yet
        keys = ["a", "b", "c"]
        i = p._ismcts_select(node, keys, [0.1, 0.7, 0.2], actor=0,
                             root_player=0)
        self.assertEqual(i, 1)  # highest-prior untried action

    def test_availability_correction_prefers_more_available(self):
        # Two fully-expanded actions with IDENTICAL visits and value, but one
        # was available far more often. The availability-corrected exploration
        # term (sqrt(avail)) gives the more-available action the higher UCB.
        p = _planner(None, uct_c=1.4)
        node = _ISNode()
        node.stats = {"a": [4, 2.0, 100], "b": [4, 2.0, 4]}
        i = p._ismcts_select(node, ["a", "b"], [0.5, 0.5], actor=0,
                             root_player=0)
        self.assertEqual(i, 0)  # "a": higher availability => higher UCB

    def test_opponent_node_flips_q(self):
        # At an opponent node the value is 1-Q, so the LOW-value-for-root edge
        # is the opponent's best and gets selected.
        p = _planner(None, uct_c=0.0)  # no exploration: pure exploitation
        node = _ISNode()
        node.stats = {"a": [4, 3.6, 4], "b": [4, 0.4, 4]}  # Q_a=.9 Q_b=.1
        # root player: picks high Q (a).
        self.assertEqual(
            p._ismcts_select(node, ["a", "b"], [0.5, 0.5], 0, 0), 0)
        # opponent actor: picks the edge that is worst for root (b).
        self.assertEqual(
            p._ismcts_select(node, ["a", "b"], [0.5, 0.5], 1, 0), 1)


class TestIsmctsBestAction(unittest.TestCase):
    def test_single_shared_statistic_most_visits(self):
        root = _ISNode()
        root.stats = {0: [5, 2.0, 20], 1: [9, 6.0, 20]}
        self.assertEqual(
            MctsPlanner._ismcts_best_action(root, [[0], [1]]), [1])

    def test_deviate_margin_keeps_greedy_prior(self):
        root = _ISNode()
        # challenger (idx1) wins visits but its mean (0.558) is within margin
        # of the incumbent greedy prior (idx0, 0.550) => stay with the prior.
        root.stats = {0: [10, 5.5, 10], 1: [12, 6.7, 10]}
        self.assertEqual(
            MctsPlanner._ismcts_best_action(root, [[0], [1]], 0.0), [1])
        self.assertEqual(
            MctsPlanner._ismcts_best_action(root, [[0], [1]], 0.05), [0])


class TestIsmctsOnScriptedBackend(unittest.TestCase):
    CFG = dict(ismcts=True, n_worlds=3, max_iterations=24, time_budget_s=30.0,
               max_root_actions=3)

    def test_finds_scripted_win(self):
        for seed in (1, 2, 3):
            p = _planner(_ScriptedBackend(), **self.CFG)
            self.assertEqual(p.plan(main_view(3), Rng(seed)), [1])

    def test_uses_single_shared_tree_not_n_worlds_trees(self):
        # The determinization pool is n_worlds begins, but the statistics live
        # in ONE shared tree: last_stats reports the shared iteration count and
        # the ismcts marker.
        p = _planner(_ScriptedBackend(), **self.CFG)
        p.plan(main_view(3), Rng(5))
        self.assertTrue(p.last_stats.get("ismcts"))
        self.assertEqual(p.last_stats["worlds"], 3)
        self.assertEqual(p.last_stats["iterations"], 24)

    def test_same_seed_same_action(self):
        a = _planner(_ScriptedBackend(), **self.CFG).plan(main_view(3), Rng(11))
        b = _planner(_ScriptedBackend(), **self.CFG).plan(main_view(3), Rng(11))
        self.assertEqual(a, b)

    def test_releases_every_search_state(self):
        backend = _ScriptedBackend()
        _planner(backend, **self.CFG).plan(main_view(3), Rng(3))
        self.assertEqual(backend.live, set())  # no leaked search states
        self.assertGreater(backend.begins, 0)

    def test_degrades_to_greedy_prior_when_no_world_builds(self):
        backend = _ExplodingBackend()
        p = _planner(backend, **self.CFG)
        action = p.plan(main_view(3), Rng(5))
        self.assertEqual(len(action), 1)
        self.assertEqual(p.degraded_count, 1)
        self.assertTrue(p.last_stats.get("degraded"))
        self.assertTrue(p.last_stats.get("ismcts"))

    def test_forced_selection_skips_search(self):
        # A single legal action never touches the ISMCTS machinery.
        view = adapt(observation(
            select([{"type": 1}], min_count=1, max_count=1)))
        p = _planner(None, **self.CFG)
        self.assertEqual(p.plan(view, Rng(1)), [0])
        self.assertTrue(p.last_stats.get("forced"))


if __name__ == "__main__":
    unittest.main()
