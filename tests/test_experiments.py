import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from busbidder.cli import EXIT_OK, main
from busbidder.experiments import EXPERIMENTS, profile_variant, with_price_weight
from tests.test_filtering import make_profile
from busbidder.logging_setup import close_logging

ROOT = Path(__file__).resolve().parent.parent


class ExperimentTestCase(unittest.TestCase):
    """Shared setup. Holds no tests, so subclasses do not run tests twice."""


    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.output = self.folder / "results"

    def tearDown(self):
        close_logging()
        self.temp.cleanup()

    def run_experiments(self, *extra):
        args = [
            "--data-dir", str(ROOT / "data"),
            "--profiles-file", str(ROOT / "config" / "profiles.json"),
            "--bookings", str(self.folder / "bookings.json"),
            "--log-dir", str(self.folder / "logs"),
            "experiments", "--output", str(self.output), *extra,
        ]
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(args)
        self.assertEqual(code, EXIT_OK)
        return out.getvalue()

    def read_csv(self, name):
        with open(self.output / name, newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))


class ExperimentCommandTests(ExperimentTestCase):

    def test_experiments_are_registered(self):
        self.assertIn("E1", EXPERIMENTS.names())
        self.assertIn("E5", EXPERIMENTS.names())

    def test_e1_three_profiles_three_winners_under_both_strategies(self):
        out = self.run_experiments("--only", "E1")
        self.assertEqual(out.count("3 different first-ranked offers for 3 profiles"), 2)
        rows = self.read_csv("e1_profile_comparison.csv")
        winners = {(r["strategy"], r["profile"]): r["offer_id"] for r in rows if r["rank"] == "1"}
        self.assertEqual(winners[("anchored", "business")], "OFR-00186")
        self.assertEqual(winners[("anchored", "flexible")], "OFR-00398")

    def test_e5_counts_match_the_invalid_file_design(self):
        self.run_experiments("--only", "E5")
        rows = self.read_csv("e5_validation_counts.csv")
        def total(file, outcome):
            return sum(int(r["count"]) for r in rows if r["file"] == file and r["outcome"] == outcome)
        self.assertEqual(total("offers_invalid.csv", "accepted"), 3)
        self.assertEqual(total("offers_invalid.csv", "rejected"), 16)
        self.assertEqual(total("offers_invalid.csv", "review"), 2)
        self.assertEqual(total("offers.csv", "accepted"), 527)
        self.assertEqual(total("offers.csv", "rejected"), 0)

    def test_only_runs_the_named_experiment(self):
        self.run_experiments("--only", "E5")
        self.assertFalse((self.output / "e1_profile_comparison.csv").exists())

    def test_running_twice_gives_identical_files(self):
        self.run_experiments()
        first = {p.name: p.read_bytes() for p in self.output.iterdir()}
        self.run_experiments()
        second = {p.name: p.read_bytes() for p in self.output.iterdir()}
        self.assertEqual(first, second)

    def test_experiments_ignore_existing_bookings(self):
        # A booking file that sells out the business winner must not change E1.
        import json
        from busbidder.booking import Booking
        from datetime import datetime
        from busbidder.models import FareConditions
        booking = Booking("BB-2026-ABCDEF", "OFR-00186", "CAM", "MAL", datetime(2026, 7, 12, 11, 30),
                          16, 76.70, FareConditions("flex", "free", True), "business",
                          datetime(2026, 10, 24, 12, 0))
        (self.folder / "bookings.json").write_text(json.dumps([booking.to_dict()]), encoding="utf-8")
        self.run_experiments("--only", "E1")
        rows = self.read_csv("e1_profile_comparison.csv")
        winner = next(r for r in rows if r["strategy"] == "anchored" and r["profile"] == "business" and r["rank"] == "1")
        self.assertEqual(winner["offer_id"], "OFR-00186")


class HelperTests(unittest.TestCase):

    def test_price_weight_keeps_other_weights_in_proportion(self):
        weights = {"price": 40, "duration": 25, "departure_time": 15, "flexibility": 20}
        self.assertEqual(with_price_weight(weights, 40), weights)
        # 30% is shared 25:15:20, giving 12.5, 7.5 and 10. Python rounds
        # halves to the nearest even number, so 12 and 8.
        self.assertEqual(
            with_price_weight(weights, 70),
            {"price": 70, "duration": 12, "departure_time": 8, "flexibility": 10},
        )

    def test_price_weight_always_totals_100(self):
        weights = {"price": 60, "duration": 15, "departure_time": 15, "flexibility": 10}
        for price_weight in range(0, 101, 10):
            with self.subTest(price_weight=price_weight):
                result = with_price_weight(weights, price_weight)
                self.assertEqual(sum(result.values()), 100)
                self.assertEqual(result["price"], price_weight)

    def test_profile_variant_leaves_original_unchanged(self):
        profile = make_profile(max_price_eur=50)
        variant = profile_variant(profile, max_price_eur=60)
        self.assertEqual((profile.max_price_eur, variant.max_price_eur), (50, 60))


class SensitivityAndCliffTests(ExperimentTestCase):

    def test_e2_marks_each_profile_own_weight(self):
        out = self.run_experiments("--only", "E2")
        self.assertEqual(out.count("<- own weight"), 3)
        rows = self.read_csv("e2_weight_sensitivity.csv")
        self.assertEqual(len([r for r in rows if r["profile"] == "budget"]), 11)
        own = next(r for r in rows if r["profile"] == "business" and r["price_weight"] == "10")
        self.assertEqual(own["winner"], "OFR-00186")

    def test_e2_fine_check_covers_every_point_around_each_own_weight(self):
        out = self.run_experiments("--only", "E2")
        rows = self.read_csv("e2_weight_sensitivity_fine.csv")
        flexible = {int(r["price_weight"]): r for r in rows if r["profile"] == "flexible"}
        self.assertEqual(sorted(flexible), list(range(15, 36)))
        self.assertEqual(flexible[25]["is_own_weight"], "True")
        self.assertEqual(flexible[25]["weights"], "price=25 duration=15 departure_time=10 flexibility=50")
        business = [int(r["price_weight"]) for r in rows if r["profile"] == "business"]
        self.assertEqual((min(business), max(business)), (0, 20))
        for r in rows:
            total = sum(int(part.split("=")[1]) for part in r["weights"].split())
            self.assertEqual(total, 100)
        self.assertIn("flexible: own price weight 25%, winner OFR-00398", out)
        self.assertIn("same winner from 15% to 35%", out)

    def test_e4_cliff_edge_removes_exactly_one_offer(self):
        self.run_experiments("--only", "E4")
        edge = [r for r in self.read_csv("e4_budget_cliff.csv") if r["part"] == "edge"]
        self.assertEqual([int(r["offers_kept"]) for r in edge], [7, 8, 8])
        self.assertEqual([r["edge_offer_kept"] for r in edge], ["False", "True", "True"])


class ReversalAndBookingTests(ExperimentTestCase):

    def test_e3_anchored_never_reverses_minmax_does(self):
        self.run_experiments("--only", "E3")
        rows = self.read_csv("e3_rank_reversal.csv")
        anchored = [r for r in rows if r["strategy"] == "anchored"]
        minmax = [r for r in rows if r["strategy"] == "minmax"]
        self.assertTrue(anchored)
        self.assertFalse(any(r["order_changed"] == "True" for r in anchored))
        reversal = [r for r in minmax if r["winner_with"] != r["winner_without"]]
        self.assertEqual(
            [(r["profile"], r["left_out"], r["winner_with"], r["winner_without"]) for r in reversal],
            [("budget", "OFR-00398", "OFR-00035", "OFR-00322")],
        )

    def test_e6_all_checks_pass_and_real_bookings_untouched(self):
        out = self.run_experiments("--only", "E6")
        self.assertIn("10 of 10 checks passed", out)
        self.assertFalse((self.folder / "bookings.json").exists())
        results = [r["result"] for r in self.read_csv("e6_booking_consistency.csv")]
        self.assertEqual(set(results), {"pass"})


if __name__ == "__main__":
    unittest.main()
