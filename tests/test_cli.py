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
