import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from busbidder.cli import EXIT_ERROR, EXIT_OK, main
from busbidder.logging_setup import close_logging

ROOT = Path(__file__).resolve().parent.parent


class CliTestCase(unittest.TestCase):
    """Runs the CLI with real data but a temporary log folder and booking file."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        close_logging()
        self.temp.cleanup()

    def run_cli(self, *args):
        base = [
            "--data-dir", str(ROOT / "data"),
            "--profiles-file", str(ROOT / "config" / "profiles.json"),
            "--bookings", str(self.folder / "bookings.json"),
            "--log-dir", str(self.folder / "logs"),
        ]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(base + list(args))
        return code, out.getvalue(), err.getvalue()


class RankCommandTests(CliTestCase):

    def test_rank_shows_profile_removals_table_and_explanation(self):
        code, out, _ = self.run_cli("rank", "--profile", "business")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Business traveller", out)
        self.assertIn("Removed 9 (9 change level", out)
        self.assertIn("OFR-00186", out)
        self.assertIn("ranked first under your preferences", out)

    def test_rank_with_minmax_strategy(self):
        code, out, _ = self.run_cli("rank", "--profile", "budget", "--strategy", "minmax")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Normalisation: minmax", out)
        self.assertIn("Close call", out)

    def test_unknown_profile_gives_error_listing_available_names(self):
        code, _, err = self.run_cli("rank", "--profile", "tourist")
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("no profile named 'tourist'", err)
        self.assertIn("budget, business, flexible", err)

    def test_unknown_strategy_is_refused_by_argparse(self):
        with self.assertRaises(SystemExit) as context:
            self.run_cli("rank", "--profile", "budget", "--strategy", "zscore")
        self.assertEqual(context.exception.code, 2)

    def test_errors_are_logged(self):
        self.run_cli("rank", "--profile", "tourist")
        log = (self.folder / "logs" / "busbidder.log").read_text(encoding="utf-8")
        self.assertIn("ERROR", log)
        self.assertIn("ConfigError", log)


class ArgumentAndStateTests(CliTestCase):

    def test_top_must_be_at_least_one(self):
        for command in (["rank", "--profile", "budget"], ["book", "--profile", "budget"],
                        ["compare", "--profiles", "budget"]):
            for bad in ("0", "-2", "abc"):
                with self.subTest(command=command[0], top=bad):
                    with self.assertRaises(SystemExit) as context:
                        self.run_cli(*command, "--top", bad)
                    self.assertEqual(context.exception.code, 2)

    def test_validate_and_experiments_ignore_a_corrupt_booking_file(self):
        (self.folder / "bookings.json").write_text("{ broken", encoding="utf-8")
        code, out, _ = self.run_cli("validate")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("527 accepted", out)
        code, _, _ = self.run_cli("experiments", "--only", "E5", "--output", str(self.folder / "results"))
        self.assertEqual(code, EXIT_OK)

    def test_rank_still_reports_a_corrupt_booking_file(self):
        (self.folder / "bookings.json").write_text("{ broken", encoding="utf-8")
        code, _, err = self.run_cli("rank", "--profile", "budget")
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("is not valid JSON", err)


class CompareCommandTests(CliTestCase):

    def test_three_profiles_give_three_different_winners(self):
        code, out, _ = self.run_cli("compare", "--profiles", "budget", "business", "flexible")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("3 profiles, 3 different first-ranked offer(s).", out)


class ValidateCommandTests(CliTestCase):

    def test_validate_invalid_file_lists_every_problem(self):
        code, out, _ = self.run_cli("--offers", str(ROOT / "data" / "offers_invalid.csv"), "validate")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("3 accepted, 16 rejected, 2 set aside for review, 2 corrections", out)
        self.assertIn("OFR-90004", out)
        self.assertIn("'ver' to 'VER'", out)

    def test_missing_offer_file_gives_error_with_path(self):
        code, _, err = self.run_cli("--offers", str(self.folder / "missing.csv"), "validate")
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("missing.csv: file not found", err)


if __name__ == "__main__":
    unittest.main()


class BookCommandTests(CliTestCase):

    def book(self, *answers, profile="business"):
        from unittest.mock import patch
        with patch("builtins.input", side_effect=list(answers)):
            return self.run_cli("book", "--profile", profile)

    def read_bookings(self):
        import json
        path = self.folder / "bookings.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def test_bad_answers_are_asked_again_then_booking_succeeds(self):
        code, out, _ = self.book("abc", "", "0", "99", "1", "", "y")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Please enter a number from 1 to 5", out)
        self.assertIn("0 is not between 1 and 5", out)
        self.assertIn("99 is not between 1 and 5", out)
        self.assertIn("Booking confirmed", out)
        bookings = self.read_bookings()
        self.assertEqual(len(bookings), 1)
        self.assertEqual(bookings[0]["offer_id"], "OFR-00186")
        self.assertRegex(bookings[0]["reference"], r"^BB-2026-[A-HJ-NP-Z2-9]{6}$")
        self.assertEqual(bookings[0]["payment_status"], "paid (simulated)")

    def test_digit_like_characters_and_signs_are_asked_again(self):
        # "\u00b2" (superscript two) passes str.isdigit() but is not a number.
        code, out, _ = self.book("\u00b2", "-1", "1.5", "q")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(out.count("Please enter a number from 1 to 5"), 2)
        self.assertIn("-1 is not between 1 and 5", out)
        self.assertEqual(self.read_bookings(), [])

    def test_empty_seat_answer_uses_profile_seats(self):
        self.book("1", "", "y", profile="flexible")
        self.assertEqual(self.read_bookings()[0]["seats"], 2)

    def test_too_many_seats_is_asked_again(self):
        # OFR-00186 has 16 seats.
        code, out, _ = self.book("1", "17", "3", "y")
        self.assertIn("17 is not between 1 and 16", out)
        self.assertEqual(self.read_bookings()[0]["seats"], 3)

    def test_q_cancels_without_saving(self):
        code, out, _ = self.book("q")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Booking cancelled", out)
        self.assertEqual(self.read_bookings(), [])

    def test_answering_no_cancels_without_saving(self):
        _, out, _ = self.book("1", "", "n")
        self.assertIn("Booking cancelled", out)
        self.assertEqual(self.read_bookings(), [])

    def test_end_of_input_cancels(self):
        from unittest.mock import patch
        with patch("builtins.input", side_effect=EOFError):
            code, out, _ = self.run_cli("book", "--profile", "business")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Booking cancelled", out)

    def test_booking_reduces_seats_left_shown_in_confirmation(self):
        _, out, _ = self.book("1", "4", "y")
        self.assertIn("Seats left on this departure: 12", out)

    def test_sold_out_offer_disappears_from_next_ranking(self):
        self.book("1", "16", "y")
        _, out, _ = self.run_cli("rank", "--profile", "business")
        self.assertNotIn("OFR-00186", out)
        self.assertIn("1 seats", out)
