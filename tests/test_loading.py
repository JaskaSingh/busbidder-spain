import tempfile
import unittest
from pathlib import Path

from busbidder.errors import DataFileError
from busbidder.loading import load_companies, load_destinations

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

    def test_duplicate_id_is_reported(self):
        path = self.write(
            "c.csv",
            "company_id,name,profile\nSOL,SolRuta,Cheap\nSOL,SolRuta again,Cheap\n",
        )
        with self.assertRaises(DataFileError) as context:
            load_companies(path)
        self.assertIn("more than once", context.exception.reason)


if __name__ == "__main__":
    unittest.main()
