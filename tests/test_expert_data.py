"""SOT-1914: expert-iteration self-play data pipeline.

Engine-independent tests (H1-H3 features, loss-cause tags, visit-distribution
extraction, schema validation, sharded merge, restart/resume) plus one
engine-gated end-to-end generation that skips when the cabt engine (cg/) is
absent (CI).
"""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from agents.cards import CardIndex
from agents.value_features import FEATURE_DIM
from agents.expert_features import (H_FEATURE_DIM, H_FEATURE_NAMES,
                                    extract_h, loss_cause)
from tests.support import observation, player, pokemon, select, \
    synthetic_card_index
from train import gen_expert_data, merge_expert_data, validate_expert_data

try:
    from cg import game  # noqa: F401
    HAS_ENGINE = True
except Exception:  # pragma: no cover - engine absent (CI)
    HAS_ENGINE = False


def _h(obs, actor=0, idx=None):
    return extract_h(obs, actor, idx or synthetic_card_index())


def _named(vec):
    return dict(zip(H_FEATURE_NAMES, vec))


class TestHFeatures(unittest.TestCase):
    def test_partial_state_is_zero_vector(self):
        obs = {"current": {"players": []}}
        self.assertEqual(_h(obs), [0.0] * H_FEATURE_DIM)

    def test_all_values_in_unit_range(self):
        obs = observation(select([{"type": 13}]),
                          me=player(active=[pokemon(102, hp=60)],
                                    bench=[pokemon(101)],
                                    hand=[{"id": 101}, {"id": 103}]),
                          opp=player(active=[pokemon(101)]))
        for k, v in _named(_h(obs)).items():
            self.assertGreaterEqual(v, 0.0, k)
            self.assertLessEqual(v, 1.0, k)

    def test_h1_bench_empty_and_wipe_exposure(self):
        # Active present, no bench, opponent Active hits (card 101 -> dmg 50)
        # vs my 60hp Active => exposure 50/60.
        obs = observation(select([{"type": 13}]),
                          me=player(active=[pokemon(102, hp=60)], bench=[]),
                          opp=player(active=[pokemon(101)]))
        f = _named(_h(obs))
        self.assertEqual(f["h1_bench_empty"], 1.0)
        self.assertAlmostEqual(f["h1_wipe_exposure"], 50.0 / 60.0, places=5)

    def test_h1_zero_when_bench_backup_present(self):
        obs = observation(select([{"type": 13}]),
                          me=player(active=[pokemon(102)],
                                    bench=[pokemon(101)]),
                          opp=player(active=[pokemon(101)]))
        f = _named(_h(obs))
        self.assertEqual(f["h1_bench_empty"], 0.0)
        self.assertEqual(f["h1_wipe_exposure"], 0.0)

    def test_h2_hand_basics_count_and_zero_flag(self):
        # hand: 101 (Basic) + 102 (Basic) + 103 (Supporter) => 2 Basics.
        obs = observation(select([{"type": 13}]),
                          me=player(active=[pokemon(101)],
                                    hand=[{"id": 101}, {"id": 102},
                                          {"id": 103}]))
        f = _named(_h(obs))
        self.assertAlmostEqual(f["h2_hand_basics"], 2.0 / 6.0, places=5)
        self.assertEqual(f["h2_hand_basics_zero"], 0.0)
        # No Basics in hand -> zero flag fires.
        obs0 = observation(select([{"type": 13}]),
                           me=player(active=[pokemon(101)],
                                     hand=[{"id": 103}]))
        self.assertEqual(_named(_h(obs0))["h2_hand_basics_zero"], 1.0)

    def test_h3_development(self):
        # 1 evolved (stage1 card 150) + 1 basic in play; energies summed.
        idx = CardIndex([SimpleNamespace(
            cardId=150, cardType=0, retreatCost=1, hp=100, weakness=None,
            resistance=None, energyType=0, basic=False, stage1=True,
            stage2=False, ex=False, megaEx=False, tera=False, aceSpec=False,
            evolvesFrom=None, skills=[], attacks=[])], [])
        obs = observation(select([{"type": 13}]),
                          me=player(active=[pokemon(150, energies=[0, 0])],
                                    bench=[pokemon(150, energies=[0])]))
        f = _named(extract_h(obs, 0, idx))
        self.assertAlmostEqual(f["h3_pokemon_in_play"], 2.0 / 6.0, places=5)
        self.assertAlmostEqual(f["h3_energy_attached"], 3.0 / 12.0, places=5)
        self.assertAlmostEqual(f["h3_evolved"], 2.0 / 6.0, places=5)


class TestLossCause(unittest.TestCase):
    def test_wipe_when_loser_has_no_pokemon(self):
        obs = observation(select([{"type": 14}]),
                          me=player(active=[pokemon(101)]),  # winner P0
                          opp=player(active=[], bench=[]))    # loser wiped
        obs["current"]["result"] = 0
        self.assertEqual(loss_cause(obs, 1, synthetic_card_index())["wipe"], 1)

    def test_wipe_when_active_but_empty_bench(self):
        obs = observation(select([{"type": 14}]),
                          me=player(active=[pokemon(101)]),
                          opp=player(active=[pokemon(101)], bench=[]))
        self.assertEqual(loss_cause(obs, 1, synthetic_card_index())["wipe"], 1)

    def test_seed_when_no_basics_in_hand(self):
        obs = observation(select([{"type": 14}]),
                          me=player(active=[pokemon(101)]),
                          opp=player(active=[pokemon(101)], bench=[pokemon(101)],
                                     hand=[{"id": 103}]))
        tags = loss_cause(obs, 1, synthetic_card_index())
        self.assertEqual(tags["seed"], 1)
        self.assertEqual(tags["wipe"], 0)  # has a bench backup


class TestVisitDistribution(unittest.TestCase):
    def _agent(self, last_stats):
        return SimpleNamespace(_planner=SimpleNamespace(last_stats=last_stats))

    def test_normalizes_visits_to_probabilities(self):
        agent = self._agent({"root_actions": [[0], [1], [2]],
                             "root_visits": [3, 5, 2]})
        pi = gen_expert_data._visit_distribution(agent)
        self.assertEqual(pi["a"], [[0], [1], [2]])
        self.assertEqual(pi["v"], [3, 5, 2])
        self.assertAlmostEqual(sum(pi["p"]), 1.0)
        self.assertAlmostEqual(pi["p"][1], 0.5)

    def test_none_when_forced_or_degraded_or_zero(self):
        self.assertIsNone(gen_expert_data._visit_distribution(
            self._agent({"forced": True})))
        self.assertIsNone(gen_expert_data._visit_distribution(
            self._agent({"root_actions": [[0]], "root_visits": [4]})))
        self.assertIsNone(gen_expert_data._visit_distribution(
            self._agent({"root_actions": [[0], [1]],
                         "root_visits": [0, 0]})))
        self.assertIsNone(gen_expert_data._visit_distribution(
            SimpleNamespace(_planner=None)))


def _good_row():
    return {"m": 0, "actor": 0, "d": 1, "f": [0.0] * FEATURE_DIM,
            "h": [0.0] * H_FEATURE_DIM,
            "pi": {"a": [[0], [1]], "v": [1, 3], "p": [0.25, 0.75]},
            "y": 1.0, "aux_wipe": 0, "aux_seed": 0}


class TestValidate(unittest.TestCase):
    def test_good_row_passes(self):
        self.assertEqual(validate_expert_data.validate_row(_good_row()), [])

    def test_catches_feature_length(self):
        r = _good_row(); r["f"] = [0.0] * (FEATURE_DIM - 1)
        self.assertTrue(any("f length" in e
                            for e in validate_expert_data.validate_row(r)))

    def test_catches_h_out_of_range(self):
        r = _good_row(); r["h"][0] = 1.5
        self.assertTrue(any("h value" in e
                            for e in validate_expert_data.validate_row(r)))

    def test_catches_pi_not_summing_to_one(self):
        r = _good_row(); r["pi"]["p"] = [0.25, 0.5]
        self.assertTrue(any("sums to" in e
                            for e in validate_expert_data.validate_row(r)))

    def test_catches_missing_label(self):
        r = _good_row(); r.pop("y")
        self.assertTrue(any("y missing" in e
                            for e in validate_expert_data.validate_row(r)))

    def test_catches_bad_aux(self):
        r = _good_row(); r["aux_wipe"] = 2
        self.assertTrue(any("aux_wipe" in e
                            for e in validate_expert_data.validate_row(r)))

    def test_validate_file_ignores_meta_and_markers(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.jsonl")
            with open(p, "w") as f:
                f.write(json.dumps({"meta": {"schema_version": 1}}) + "\n")
                f.write(json.dumps(_good_row()) + "\n")
                f.write(json.dumps({"match_done": 0}) + "\n")
            n, errs = validate_expert_data.validate_file(p)
            self.assertEqual(n, 1)
            self.assertEqual(errs, [])


class TestResumeAndMerge(unittest.TestCase):
    def _write(self, path, rows, done):
        with open(path, "a") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            for m in done:
                f.write(json.dumps({"match_done": m}) + "\n")

    def test_scan_completed_and_drop_incomplete_match(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            # match 0 complete; match 1 has rows but NO match_done (crash).
            r0 = _good_row(); r0["m"] = 0
            r1 = _good_row(); r1["m"] = 1
            self._write(p, [r0], done=[0])
            self._write(p, [r1], done=[])   # incomplete
            self.assertEqual(gen_expert_data.scan_completed(p), {0})
            rows, completed = gen_expert_data.read_expert_rows(p)
            self.assertEqual(completed, {0})
            self.assertEqual([r["m"] for r in rows], [0])  # match 1 dropped

    def test_merge_unions_completed_rows_and_aggregates_meta(self):
        with tempfile.TemporaryDirectory() as d:
            s0 = os.path.join(d, "expert.shard0.jsonl")
            s1 = os.path.join(d, "expert.shard1.jsonl")
            out = os.path.join(d, "merged.jsonl")
            a = _good_row(); a["m"] = 0
            b = _good_row(); b["m"] = 1; b["y"] = 0.0; b["aux_wipe"] = 1
            self._write(s0, [a], done=[0])
            self._write(s1, [b], done=[1])
            for path, shard in ((s0, 0), (s1, 1)):
                with open(path + ".meta.json", "w") as mf:
                    json.dump({"schema_version": 1, "feature_version": 1,
                               "h_feature_version": 1, "seed": 7,
                               "shard_index": shard, "n_shards": 2,
                               "matches_played": 5, "faults": 0,
                               "gen_seconds": 100.0, "games_per_hour": 180.0},
                              mf)
            meta = merge_expert_data.main_argv(["--out", out, s0, s1])
            self.assertEqual(meta["samples"], 2)
            self.assertEqual(meta["win_samples"], 1)
            self.assertEqual(meta["aux_wipe_samples"], 1)
            self.assertEqual(meta["matches_played"], 10)
            self.assertEqual(meta["matches_done"], 2)
            with open(out) as f:
                lines = [l for l in f.read().splitlines() if l]
            self.assertIn("meta", json.loads(lines[0]))
            self.assertEqual(len(lines) - 1, 2)  # meta + 2 rows

    def test_merge_rejects_version_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            s0 = os.path.join(d, "bad.shard0.jsonl")
            out = os.path.join(d, "m.jsonl")
            self._write(s0, [_good_row()], done=[0])
            with open(s0 + ".meta.json", "w") as mf:
                json.dump({"schema_version": 999}, mf)
            with self.assertRaises(SystemExit):
                merge_expert_data.main_argv(["--out", out, s0])


class TestShardPartition(unittest.TestCase):
    def test_shards_partition_match_space(self):
        n, M = 500, 8
        owned = [set(i for i in range(n) if i % M == k) for k in range(M)]
        for a in range(M):
            for b in range(a + 1, M):
                self.assertEqual(owned[a] & owned[b], set())
        self.assertEqual(set().union(*owned), set(range(n)))


@unittest.skipUnless(HAS_ENGINE, "cabt engine (cg/) not available")
class TestGenExpertOnEngine(unittest.TestCase):
    """End-to-end: a small real generation runs fault-0 and every row passes
    schema validation (visit distribution sums to 1, labels present, H1-H3 in
    range)."""

    FAST = dict(n_worlds=2, max_iterations=16, time_budget_s=5.0,
                rollout_turns=1, rollout_depth=20, max_root_actions=4,
                max_child_actions=4)

    def test_generation_is_fault0_and_schema_valid(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "expert.jsonl")
            meta = gen_expert_data.generate(
                "mcts", n=4, seed=20260725, deck_path="deck.csv",
                stride=1, max_per_match=200, aux_horizon=8, out=out,
                config=self.FAST)
            self.assertEqual(meta["faults"], 0)          # fault 0
            self.assertGreater(meta["matches_played"], 0)
            n_rows, errors = validate_expert_data.validate_file(out)
            self.assertEqual(errors, [], f"schema errors: {errors}")
            self.assertGreater(n_rows, 0, "no policy samples recorded")

    def test_resume_skips_completed_matches(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "expert.jsonl")
            gen_expert_data.generate(
                "mcts", n=2, seed=1, deck_path="deck.csv", stride=1,
                max_per_match=200, aux_horizon=8, out=out, config=self.FAST)
            done_first = gen_expert_data.scan_completed(out)
            # Re-run the SAME shard spec: all matches already done -> 0 replayed.
            meta2 = gen_expert_data.generate(
                "mcts", n=2, seed=1, deck_path="deck.csv", stride=1,
                max_per_match=200, aux_horizon=8, out=out, config=self.FAST)
            self.assertEqual(meta2["matches_played"], 0)
            self.assertEqual(meta2["matches_resumed"], len(done_first))


if __name__ == "__main__":
    unittest.main()
