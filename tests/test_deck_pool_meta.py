"""Tests for the meta-driven deck-pool tooling (SOT-2055).

These are engine-independent: snapshot parsing, multi-signal analysis, selection
invariants, legality, and the apply/rollback round-trip all run without cg/. The
legality-against-real-card-data check self-skips when the licensed card CSV is
absent (mirroring the engine tests' self-skip convention).

Run under the repo's ``unittest discover`` suite, or standalone:
    venv/bin/python -m unittest tests.test_deck_pool_meta -v
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from tools import deck_legality, deck_map, deck_selection, meta_analysis
from tools import deck_update
from tools import meta_snapshot as ms

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(REPO, "decks", "meta", "snapshots")


def load_snaps():
    return deck_update.load_snapshots(SNAP_DIR)


class TestSnapshotParsing(unittest.TestCase):
    def test_committed_snapshots_have_three_separate_bands(self):
        snaps = load_snaps()
        self.assertGreaterEqual(len(snaps), 3, "need >=3 snapshots for trend")
        for s in snaps:
            bands = s["bands"]
            self.assertIn("top10", bands)
            self.assertIn("top20", bands)
            self.assertIn("top100", bands)
            # Top100 is a ranked list; Top10/Top20 are name->{teams,share} maps.
            self.assertIsInstance(bands["top100"], list)
            self.assertTrue(bands["top100"], "Top100 must be non-empty")
            for row in bands["top100"]:
                self.assertIn("rank", row)
                self.assertIn("share", row)

    def test_latest_snapshot_marnie_dominant(self):
        snaps = load_snaps()
        latest = snaps[-1]
        # As of 2026-07-27 Marnie's Grimmsnarl leads the Top100.
        top = latest["bands"]["top100"][0]
        self.assertEqual(top["rank"], 1)
        self.assertGreater(top["share"], 40.0)

    def test_band_helpers(self):
        snaps = load_snaps()
        latest = snaps[-1]
        arch = latest["bands"]["top100"][0]["archetype"]
        self.assertGreater(ms.top100_share(latest, arch), 0)
        self.assertEqual(ms.top100_rank(latest, arch), 1)
        self.assertEqual(ms.top100_share(latest, "no-such-archetype"), 0.0)


class TestMetaAnalysis(unittest.TestCase):
    def setUp(self):
        self.signals = meta_analysis.analyze(load_snaps())

    def test_signals_cover_bands_rank_trend_continuity(self):
        marnie = self.signals["マリィのオーロンゲex"]
        for key in ("latest_top100_share", "latest_top10_share",
                    "latest_top20_share", "latest_top100_rank",
                    "trend_slope", "snapshots_present", "trailing_consecutive",
                    "lb_best_rank"):
            self.assertIn(key, marnie)
        # Marnie's share rose across the window -> positive trend.
        self.assertGreater(marnie["trend_slope"], 0)
        self.assertEqual(marnie["latest_top100_rank"], 1)

    def test_low_usage_high_rank_flag(self):
        # Raging Bolt (タケルライコex) sits high on the board yet low in Top100.
        rb = self.signals.get("タケルライコex")
        self.assertIsNotNone(rb)
        self.assertTrue(rb["low_usage_high_rank"])
        self.assertLess(rb["latest_top100_share"], meta_analysis.LOW_USAGE_SHARE)

    def test_not_usage_only_board_leader_scores(self):
        # A board leader with tiny share must still outscore a pure off-meta 0.
        rb = self.signals.get("タケルライコex")
        self.assertGreater(meta_analysis.meta_score(rb), 0)


class TestSelection(unittest.TestCase):
    def setUp(self):
        self.rows = deck_map.library_rows()
        self.signals = meta_analysis.analyze(load_snaps())
        self.prior = deck_update.detect_prior_active()
        self.plan = deck_selection.plan(
            self.rows, self.signals, self.prior,
            target_size=None, max_churn_frac=0.25, max_per_arch=2, seed=0)

    def test_count_never_grows_and_reapply_is_stable(self):
        # claude's deck count is delegated to this reorg (no preservation
        # constraint): the pool may *shrink* when over-concentrated near-
        # duplicates are dropped, but it never grows beyond the prior pool...
        self.assertLessEqual(self.plan["active_count"], self.plan["prior_count"])
        # ...and re-planning from the just-computed pool is a fixed point.
        again = deck_selection.plan(
            self.rows, self.signals, self.plan["active"],
            target_size=None, max_churn_frac=0.25, max_per_arch=2, seed=0)
        self.assertEqual(again["active_count"], self.plan["active_count"])
        self.assertEqual(again["churn"], 0)

    def test_churn_within_25_percent(self):
        self.assertLessEqual(self.plan["churn"], self.plan["max_changes"])
        self.assertLessEqual(self.plan["max_changes"],
                             int(0.25 * self.plan["prior_count"]))

    def test_no_archetype_over_concentrated(self):
        counts = {}
        for f in self.plan["active"]:
            mk = self.plan["detail"][f]["meta_key"]
            if mk:
                counts[mk] = counts.get(mk, 0) + 1
        for mk, c in counts.items():
            self.assertLessEqual(c, 2, f"{mk} over-concentrated ({c})")

    def test_role_coverage_preserved(self):
        roles = [self.plan["detail"][f]["role"] for f in self.plan["active"]]
        self.assertIn("low_usage_top", roles, "board-leader deck must survive")
        self.assertGreaterEqual(roles.count("counter"),
                                deck_selection.MIN_COUNTERS,
                                "claude keeps its upper-meta resistance role")

    def test_present_upper_meta_archetypes_covered(self):
        active_keys = {self.plan["detail"][f]["meta_key"]
                       for f in self.plan["active"]}
        for mk, sig in self.signals.items():
            if float(sig["latest_top100_share"]) >= 5.0 and mk in {
                    r["meta_key"] for r in self.rows}:
                self.assertIn(mk, active_keys,
                              f"top archetype {mk} not covered")

    def test_every_change_has_a_reason(self):
        for f in self.plan["added"]:
            self.assertTrue(self.plan["detail"][f]["reason"])
        for f in self.plan["removed"]:
            # removed files are library decks, so a reason exists
            self.assertIn(f, self.plan["detail"])
            self.assertTrue(self.plan["detail"][f]["reason"])

    def test_deterministic(self):
        again = deck_selection.plan(
            self.rows, self.signals, self.prior,
            target_size=None, max_churn_frac=0.25, max_per_arch=2, seed=0)
        self.assertEqual(self.plan["active"], again["active"])

    def test_seed_is_reproducible_but_may_reorder_ties(self):
        other = deck_selection.plan(
            self.rows, self.signals, self.prior,
            target_size=None, max_churn_frac=0.25, max_per_arch=2, seed=7)
        # Same knobs + same seed is stable; different seed stays a valid plan.
        self.assertEqual(other["active_count"], self.plan["active_count"])
        self.assertLessEqual(other["churn"], other["max_changes"])


class TestLegality(unittest.TestCase):
    def test_checker_rejects_illegal_decks(self):
        pool = {
            1: {"name": "Basic {G} Energy", "stage_type": "Basic Energy", "rule": ""},
            100: {"name": "Foo", "stage_type": "Basic", "rule": ""},
            200: {"name": "AceA", "stage_type": "Item", "rule": "ACE SPEC"},
            201: {"name": "AceB", "stage_type": "Item", "rule": "ACE SPEC"},
        }
        # 5 copies of a non-energy card -> illegal
        over = deck_legality.check_deck([100] * 5 + [1] * 55, pool)
        self.assertFalse(over["legal"])
        # 2 ACE SPEC -> illegal
        ace = deck_legality.check_deck([200, 201] + [1] * 58, pool)
        self.assertFalse(ace["legal"])
        # basic energy may exceed 4
        ok = deck_legality.check_deck([1] * 60, pool)
        self.assertTrue(ok["legal"])
        # wrong count
        self.assertFalse(deck_legality.check_deck([1] * 59, pool)["legal"])

    def test_all_active_decks_are_legal(self):
        try:
            pool = deck_legality.load_card_pool()
        except deck_legality.CardDataUnavailable:
            self.skipTest("card data unavailable")
        manifest_path = deck_update.ACTIVE_MANIFEST
        if not os.path.exists(manifest_path):
            self.skipTest("no applied active manifest")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        for d in manifest["decks"]:
            path = os.path.join(REPO, "decks", d["source_group"], d["file"])
            ids = deck_legality.load_deck_ids(path)
            report = deck_legality.check_deck(ids, pool)
            self.assertTrue(report["legal"],
                            f"{d['file']} illegal: {report['problems']}")


class TestApplyRollbackRoundTrip(unittest.TestCase):
    def test_apply_then_rollback_restores_candidate_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            active_dir = os.path.join(tmp, "meta_active")
            os.makedirs(active_dir)
            with mock.patch.multiple(
                    deck_update,
                    ACTIVE_DIR=active_dir,
                    ACTIVE_MANIFEST=os.path.join(active_dir, "manifest.json"),
                    ROLLBACK_DIR=os.path.join(active_dir, "rollback")):
                plan = deck_update.compute_plan(None, 0.25, 2, 0)
                # From the full candidate library the reorg may de-duplicate
                # (shrink), never grow beyond it.
                self.assertLessEqual(plan["active_count"], plan["prior_count"])
                rb = deck_update.apply_plan(plan, 0)
                self.assertTrue(os.path.exists(deck_update.ACTIVE_MANIFEST))
                csvs = [f for f in os.listdir(active_dir) if f.endswith(".csv")]
                self.assertEqual(len(csvs), plan["active_count"])
                deck_update.rollback(rb)
                self.assertFalse(os.path.exists(deck_update.ACTIVE_MANIFEST))
                csvs = [f for f in os.listdir(active_dir) if f.endswith(".csv")]
                self.assertEqual(csvs, [])


if __name__ == "__main__":
    unittest.main()
