import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from busbidder.cli import EXIT_OK, main
from busbidder.experiments import EXPERIMENTS
from busbidder.logging_setup import close_logging

ROOT = Path(__file__).resolve().parent.parent


class ExperimentCommandTests(unittest.TestCase):

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


if __name__ == "__main__":
    unittest.main()
