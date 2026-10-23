"""End-to-end test of the whole pipeline on a small hand-made dataset.

tests/fixtures/pipeline holds ten offers designed so that every stage has a
known result:

    OFR-00001  SolRuta basic, EUR 30, 09:00, 7 h 30       accepted
    OFR-00002  VerdeBus free change, EUR 45, 2 seats left  accepted, ranked first
    OFR-00003  Camino Express, EUR 55                      removed: budget
    OFR-00004  CostaLink, 1 seat left                      removed: seats (2 needed)
    OFR-00005  NocheVia, 22:00, 1 transfer                 accepted
    OFR-00006  on 14 July                                  out of scope: date
    OFR-00007  to Toledo                                   out of scope: destination
    OFR-00008  price -5                                    rejected by validation
    OFR-00009  price EUR 1.00                              set aside for review
    OFR-00010  2 transfers                                 removed: transfers

Expected totals, worked out by hand with weights 40/25/15/20, budget EUR 50
and a fastest plausible time of 530 / 95 * 60 = 334.7 minutes:

    VerdeBus:  0.40*10 + 0.25*92.4 + 0.15*100 + 0.20*100 = 62.1
    SolRuta:   0.40*40 + 0.25*65.6 + 0.15*100 + 0.20*0   = 47.4
    NocheVia:  0.40*36 + 0.25*52.1 + 0.15*0   + 0.20*50  = 37.4
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from busbidder.cli import EXIT_OK, main
from busbidder.logging_setup import close_logging

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pipeline"


class PipelineTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.bookings_path = self.folder / "state" / "bookings.json"
        self.log_path = self.folder / "logs" / "busbidder.log"

    def tearDown(self):
        close_logging()
        self.temp.cleanup()

    def run_cli(self, *args, answers=None):
        base = [
            "--data-dir", str(FIXTURES),
            "--profiles-file", str(FIXTURES / "profiles.json"),
            "--bookings", str(self.bookings_path),
            "--log-dir", str(self.log_path.parent),
        ]
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            if answers is None:
                code = main(base + list(args))
            else:
                with patch("builtins.input", side_effect=answers):
                    code = main(base + list(args))
        self.assertEqual(code, EXIT_OK)
        return out.getvalue()

    def ranked_ids(self, output):
        """Offer IDs in the order they appear in the ranking table."""
        rows = [line.split() for line in output.splitlines()]
        return [row[1] for row in rows if len(row) > 1 and row[0].isdigit() and row[1].startswith("OFR-")]

    def test_validation_stage(self):
        out = self.run_cli("validate")
        self.assertIn("8 accepted, 1 rejected, 1 set aside for review, 0 corrections", out)
        self.assertIn("OFR-00008", out)
        self.assertIn("OFR-00009", out)

    def test_filtering_and_ranking_stage(self):
        out = self.run_cli("rank", "--profile", "test")
        self.assertIn("6 offers match the route and dates. Removed 3 (1 budget, 1 seats, 1 transfers). 3 remain.", out)
        self.assertEqual(self.ranked_ids(out), ["OFR-00002", "OFR-00001", "OFR-00005"])
        self.assertIn("62.1", out)
        self.assertIn("47.4", out)
        self.assertIn("37.4", out)
        self.assertIn("VerdeBus OFR-00002 ranked first under your preferences", out)

    def test_booking_saves_result_and_changes_later_rankings(self):
        # Book both remaining seats on the first-ranked offer.
        out = self.run_cli("book", "--profile", "test", answers=["1", "", "y"])
        self.assertIn("Booking confirmed", out)
        self.assertIn("Seats left on this departure: 0", out)

        # The saved result.
        saved = json.loads(self.bookings_path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 1)
        booking = saved[0]
        self.assertEqual(booking["offer_id"], "OFR-00002")
        self.assertEqual(booking["seats"], 2)
        self.assertEqual(booking["total_price_eur"], 90.0)
        self.assertEqual((booking["changeable"], booking["refundable"]), ("free", True))
        self.assertRegex(booking["reference"], r"^BB-2026-[A-HJ-NP-Z2-9]{6}$")

        # The source data is untouched.
        self.assertIn(",2,4.2,6.4", (FIXTURES / "offers.csv").read_text(encoding="utf-8"))

        # A new run reads the bookings: the sold-out offer is removed and
        # the order of the others is unchanged.
        out = self.run_cli("rank", "--profile", "test")
        self.assertIn("Removed 4 (2 seats, 1 budget, 1 transfers). 2 remain.", out)
        self.assertEqual(self.ranked_ids(out), ["OFR-00001", "OFR-00005"])

        # Every stage left a trace in the log.
        log = self.log_path.read_text(encoding="utf-8")
        self.assertIn("Rejected", log)
        self.assertIn("Set aside for review", log)
        self.assertIn(f"Booked {booking['reference']}", log)

    def test_cancelled_booking_changes_nothing(self):
        self.run_cli("book", "--profile", "test", answers=["1", "", "n"])
        self.assertFalse(self.bookings_path.exists())
        out = self.run_cli("rank", "--profile", "test")
        self.assertEqual(self.ranked_ids(out), ["OFR-00002", "OFR-00001", "OFR-00005"])


if __name__ == "__main__":
    unittest.main()
