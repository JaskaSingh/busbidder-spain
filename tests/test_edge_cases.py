"""Missing-data and boundary cases not covered by the module tests.

The module tests already cover most boundaries (price exactly at budget,
transfers at the maximum, the last seat, [40, 40, 40] under min-max, ties).
This file fills the remaining gaps from the test plan.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from busbidder.booking import BookingStore
from busbidder.cli import EXIT_ERROR, EXIT_OK, main
from busbidder.criteria import departure_time_score
from busbidder.errors import DataFileError
from busbidder.filtering import constraints_for, filter_offers
from busbidder.loading import load_companies, load_destinations, load_offers
from busbidder.logging_setup import close_logging
from busbidder.scoring import rank_offers
from tests.test_filtering import make_profile
from tests.test_models import make_offer

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pipeline"
OFFER_HEADER = (
    "offer_id,company_id,fare_type,destination_id,departure_date,departure_time,"
    "arrival_date,arrival_time,price_eur,transfers,luggage_kg,changeable,refundable,"
    "available_seats,rating,co2_kg\n"
)


class TempFolderTestCase(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.companies = load_companies(DATA_DIR / "companies.csv")
        self.destinations = load_destinations(DATA_DIR / "destinations.csv")

    def tearDown(self):
        close_logging()
        self.temp.cleanup()

    def write(self, name, text):
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *args, profiles_file=None, data_dir=FIXTURES, answers=None):
        base = [
            "--data-dir", str(data_dir),
            "--profiles-file", str(profiles_file or FIXTURES / "profiles.json"),
            "--bookings", str(self.folder / "bookings.json"),
            "--log-dir", str(self.folder / "logs"),
        ]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            if answers is None:
                code = main(base + list(args))
            else:
                with patch("builtins.input", side_effect=answers):
                    code = main(base + list(args))
        return code, out.getvalue(), err.getvalue()


class MissingDataTests(TempFolderTestCase):

    def test_offer_file_missing_a_column_is_reported(self):
        header = OFFER_HEADER.replace(",co2_kg", "")
        path = self.write("offers.csv", header)
        with self.assertRaises(DataFileError) as context:
            load_offers(path, self.companies, self.destinations)
        self.assertIn("co2_kg", context.exception.reason)

    def test_offer_file_with_only_a_header_loads_nothing(self):
        result = load_offers(self.write("offers.csv", OFFER_HEADER), self.companies, self.destinations)
        self.assertEqual((result.offers, result.rejected, result.review), ([], [], []))

    def test_missing_emissions_load_as_none_and_still_rank(self):
        result = load_offers(DATA_DIR / "offers.csv", self.companies, self.destinations)
        solruta = [offer for offer in result.offers if offer.company.company_id == "SOL"]
        self.assertTrue(solruta)
        self.assertTrue(all(offer.co2_kg is None for offer in solruta))
        ranking = rank_offers(solruta[:5], make_profile(max_price_eur=200, destination_id="BAR"))
        self.assertEqual(len(ranking), 5)

    def test_missing_profile_file_gives_clear_error(self):
        code, _, err = self.run_cli("rank", "--profile", "test", profiles_file=self.folder / "none.json")
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("none.json: file not found", err)

    def test_missing_companies_file_gives_clear_error(self):
        code, _, err = self.run_cli("validate", data_dir=self.folder)
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("companies.csv: file not found", err)

    def test_corrupt_booking_file_gives_clear_error(self):
        self.write("bookings.json", "{ broken")
        code, _, err = self.run_cli("rank", "--profile", "test")
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("bookings.json: is not valid JSON", err)


class BoundaryTests(TempFolderTestCase):

    def test_departure_exactly_on_window_edges_scores_100(self):
        profile = make_profile()  # window 07:00 to 11:00
        for hour in (7, 11):
            offer = make_offer(
                departure=datetime(2026, 7, 13, hour, 0), arrival=datetime(2026, 7, 13, 19, 0)
            )
            with self.subTest(hour=hour):
                self.assertEqual(departure_time_score(offer, profile), 100)

    def test_one_minute_outside_window_scores_below_100(self):
        offer = make_offer(
            departure=datetime(2026, 7, 13, 11, 1), arrival=datetime(2026, 7, 13, 19, 0)
        )
        self.assertLess(departure_time_score(offer, make_profile()), 100)

    def test_all_offers_filtered_out_gives_clear_message(self):
        data = json.loads((FIXTURES / "profiles.json").read_text(encoding="utf-8"))
        data["test"]["max_price_eur"] = 1
        profiles = self.write("profiles.json", json.dumps(data))
        code, out, _ = self.run_cli("rank", "--profile", "test", profiles_file=profiles)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("0 remain", out)
        self.assertIn("No offers meet all hard constraints.", out)

        code, out, _ = self.run_cli("book", "--profile", "test", profiles_file=profiles, answers=[])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Nothing can be booked", out)

    def test_single_offer_under_minmax_scores_100_on_every_criterion(self):
        # Documented weakness of min-max: a lone offer looks perfect.
        ranking = rank_offers([make_offer(price_eur=49)], make_profile(), "minmax")
        self.assertEqual(set(ranking[0].scores.values()), {100.0})
        self.assertEqual(ranking[0].total, 100)
        anchored = rank_offers([make_offer(price_eur=49)], make_profile())
        self.assertLess(anchored[0].total, 100)

    def test_seats_left_exactly_equal_to_party_size_is_kept(self):
        store = BookingStore(self.folder / "bookings.json")
        offer = make_offer(
            available_seats=5, departure=datetime(2026, 7, 13, 9, 0), arrival=datetime(2026, 7, 13, 16, 0)
        )
        store.book(offer, 3, "test", booked_at=datetime(2026, 10, 24, 9, 0))
        profile = make_profile(seats_needed=2)
        self.assertEqual(filter_offers([offer], constraints_for(profile, store.seats_left)).accepted, [offer])
        profile = make_profile(seats_needed=3)
        self.assertEqual(filter_offers([offer], constraints_for(profile, store.seats_left)).accepted, [])

    def test_zero_budget_scores_free_tickets_100_and_others_0(self):
        from busbidder.criteria import price_score
        profile = make_profile(max_price_eur=0)
        self.assertEqual(price_score(make_offer(price_eur=0), profile), 100)
        self.assertEqual(price_score(make_offer(price_eur=5), profile), 0)


if __name__ == "__main__":
    unittest.main()
