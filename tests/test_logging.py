import logging
import tempfile
import unittest
from pathlib import Path

from busbidder.loading import load_companies, load_destinations, load_offers
from busbidder.logging_setup import close_logging, configure_logging

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class LogFileTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.log_path = configure_logging(self.temp.name)
        companies = load_companies(DATA_DIR / "companies.csv")
        destinations = load_destinations(DATA_DIR / "destinations.csv")
        load_offers(DATA_DIR / "offers_invalid.csv", companies, destinations)

    def tearDown(self):
        close_logging()
        self.temp.cleanup()

    def read_log(self):
        return self.log_path.read_text(encoding="utf-8")

    def test_log_file_is_created_in_the_given_folder(self):
        self.assertTrue(self.log_path.exists())
        self.assertEqual(self.log_path.name, "busbidder.log")

    def test_rejections_reviews_and_corrections_are_logged(self):
        log = self.read_log()
        self.assertEqual(log.count("Rejected "), 16)
        self.assertEqual(log.count("Set aside for review"), 2)
        self.assertEqual(log.count("Corrected "), 2)
        self.assertIn("OFR-90004", log)

    def test_counts_are_logged_at_info_level(self):
        log = self.read_log()
        self.assertIn("Loaded 5 records", log)
        self.assertIn("3 accepted, 16 rejected, 2 set aside for review", log)
        self.assertIn("WARNING", log)
        self.assertIn("INFO", log)

    def test_configuring_twice_does_not_duplicate_lines(self):
        configure_logging(self.temp.name)
        logging.getLogger("busbidder.test").info("marker line")
        self.assertEqual(self.read_log().count("marker line"), 1)


class NoConfigurationTests(unittest.TestCase):

    def test_library_logs_nothing_to_terminal_without_configuration(self):
        handlers = logging.getLogger("busbidder").handlers
        self.assertTrue(any(isinstance(h, logging.NullHandler) for h in handlers))


if __name__ == "__main__":
    unittest.main()
