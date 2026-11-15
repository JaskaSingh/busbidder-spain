import tempfile
import unittest
from pathlib import Path

from busbidder.errors import DataFileError
from busbidder.loading import load_companies, load_destinations, load_offers

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class TempFileTestCase(unittest.TestCase):
    """Gives each test a temporary folder for small hand-made CSV files."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        return path


class ReferenceDataTests(TempFileTestCase):

    def test_real_files_load(self):
        companies = load_companies(DATA_DIR / "companies.csv")
        destinations = load_destinations(DATA_DIR / "destinations.csv")
        self.assertEqual(len(companies), 5)
        self.assertEqual(len(destinations), 15)
        self.assertEqual(companies["NOC"].name, "NocheVia")
        self.assertEqual(destinations["TOL"].distance_km, 72)
        self.assertTrue(destinations["CAD"].coastal)

    def test_codes_are_cleaned(self):
        path = self.write("d.csv", "destination_id,name,distance_km,coastal\n mal ,Malaga,530,yes\n")
        self.assertIn("MAL", load_destinations(path))

    def test_missing_file_names_the_path(self):
        missing = self.folder / "nowhere.csv"
        with self.assertRaises(DataFileError) as context:
            load_companies(missing)
        self.assertEqual(context.exception.path, str(missing))
        self.assertIn("not found", context.exception.reason)

    def test_empty_file_is_reported(self):
        path = self.write("c.csv", "")
        with self.assertRaises(DataFileError) as context:
            load_companies(path)
        self.assertIn("empty", context.exception.reason)

    def test_missing_column_is_reported(self):
        path = self.write("d.csv", "destination_id,name,coastal\nMAL,Malaga,yes\n")
        with self.assertRaises(DataFileError) as context:
            load_destinations(path)
        self.assertIn("distance_km", context.exception.reason)

    def test_bad_row_stops_loading_and_names_the_line(self):
        path = self.write(
            "d.csv",
            "destination_id,name,distance_km,coastal\nMAL,Malaga,530,yes\nTOL,Toledo,-72,no\n",
        )
        with self.assertRaises(DataFileError) as context:
            load_destinations(path)
        self.assertIn("line 3", context.exception.reason)
        self.assertIn("distance_km", context.exception.reason)

    def test_reference_row_with_extra_or_missing_field_is_reported(self):
        for row in ("SOL,SolRuta,Cheap,EXTRA", "SOL,SolRuta"):
            path = self.write("c.csv", f"company_id,name,profile\n{row}\n")
            with self.subTest(row=row):
                with self.assertRaises(DataFileError) as context:
                    load_companies(path)
                self.assertIn("line 2", context.exception.reason)
                self.assertIn("wrong number of fields", context.exception.reason)

    def test_repeated_column_name_is_reported(self):
        path = self.write("c.csv", "company_id,name,profile,name\nSOL,SolRuta,Cheap,Other\n")
        with self.assertRaises(DataFileError) as context:
            load_companies(path)
        self.assertIn("used more than once: name", context.exception.reason)

    def test_duplicate_id_is_reported(self):
        path = self.write(
            "c.csv",
            "company_id,name,profile\nSOL,SolRuta,Cheap\nSOL,SolRuta again,Cheap\n",
        )
        with self.assertRaises(DataFileError) as context:
            load_companies(path)
        self.assertIn("more than once", context.exception.reason)


class OfferLoadingTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.companies = load_companies(DATA_DIR / "companies.csv")
        cls.destinations = load_destinations(DATA_DIR / "destinations.csv")
        cls.invalid = load_offers(DATA_DIR / "offers_invalid.csv", cls.companies, cls.destinations)

    def test_generated_offers_all_load_cleanly(self):
        result = load_offers(DATA_DIR / "offers.csv", self.companies, self.destinations)
        self.assertEqual(len(result.offers), 527)
        self.assertEqual(result.rejected, [])
        self.assertEqual(result.review, [])

    def test_every_row_of_invalid_file_ends_up_in_exactly_one_place(self):
        total = len(self.invalid.offers) + len(self.invalid.rejected) + len(self.invalid.review)
        self.assertEqual(total, 21)

    def test_valid_sold_out_and_corrected_rows_are_accepted(self):
        accepted = [offer.offer_id for offer in self.invalid.offers]
        self.assertEqual(accepted, ["OFR-90001", "OFR-90002", "OFR-90003"])

    def test_each_invalid_row_is_rejected_for_the_expected_field(self):
        expected = {
            5: "price_eur",        # negative price
            6: "destination_id",   # unknown destination
            7: "company_id",       # unknown company
            8: "departure_date",   # 30 February
            9: "departure_time",   # 25:10
            10: "arrival",         # arrival before departure
            11: "rating",          # 6.0 on a 1 to 5 scale
            12: "offer_id",        # malformed ID
            13: "price_eur",       # missing value
            14: "row",             # too few columns
            15: "price_eur",       # not a number
            16: "price_eur",       # nan
            17: "available_seats", # negative seats
            18: "transfers",       # negative transfers
            19: "changeable",      # unknown option
            20: "offer_id",        # duplicate ID
        }
        actual = {issue.line: issue.field for issue in self.invalid.rejected}
        self.assertEqual(actual, expected)

    def test_suspicious_rows_go_to_review(self):
        actual = {issue.line: issue.field for issue in self.invalid.review}
        self.assertEqual(actual, {21: "price_eur", 22: "duration"})

    def test_code_corrections_are_recorded(self):
        corrections = {(c.field, c.original, c.corrected) for c in self.invalid.corrections}
        self.assertEqual(
            corrections,
            {("company_id", "ver", "VER"), ("destination_id", " mal ", "MAL")},
        )

    def test_missing_offer_file_raises_file_error(self):
        with self.assertRaises(DataFileError):
            load_offers(DATA_DIR / "missing_offers.csv", self.companies, self.destinations)


if __name__ == "__main__":
    unittest.main()
