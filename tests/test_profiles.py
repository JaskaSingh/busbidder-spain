import copy
import json
import tempfile
import unittest
from datetime import date, time
from pathlib import Path

from busbidder.errors import ConfigError, DataFileError, InvalidValueError
from busbidder.profiles import load_profiles, validate_weights

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

VALID_PROFILE = {
    "label": "Test traveller",
    "destination_id": "MAL",
    "earliest_date": "2026-07-12",
    "latest_date": "2026-07-14",
    "max_price_eur": 50,
    "seats_needed": 1,
    "max_transfers": 1,
    "min_change_level": "none",
    "max_duration_minutes": None,
    "preferred_departure_from": "07:00",
    "preferred_departure_to": "11:00",
    "weights": {"price": 40, "duration": 25, "departure_time": 15, "flexibility": 20},
}


class WeightTests(unittest.TestCase):

    def test_weights_totalling_100_are_accepted(self):
        weights = {"price": 40, "duration": 25, "departure_time": 15, "flexibility": 20}
        self.assertEqual(validate_weights(weights), weights)

    def test_zero_weight_is_allowed(self):
        validate_weights({"price": 100, "duration": 0})

    def test_wrong_total_is_rejected_not_rescaled(self):
        for weights in ({"price": 40, "duration": 50}, {"price": 60, "duration": 50}):
            with self.subTest(weights=weights):
                with self.assertRaises(InvalidValueError):
                    validate_weights(weights)

    def test_negative_fractional_and_boolean_weights_are_rejected(self):
        for bad in (-10, 40.5, True, "40"):
            with self.subTest(weight=bad):
                with self.assertRaises(InvalidValueError):
                    validate_weights({"price": bad, "duration": 60})

    def test_unknown_criterion_name_is_rejected(self):
        with self.assertRaises(InvalidValueError) as context:
            validate_weights({"price": 50, "comfort": 50})
        self.assertIn("not a known criterion", context.exception.reason)

    def test_empty_weights_are_rejected(self):
        with self.assertRaises(InvalidValueError):
            validate_weights({})


class ProfileFileTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_profile(self, **changes):
        profile = copy.deepcopy(VALID_PROFILE)
        profile.update(changes)
        path = self.folder / "profiles.json"
        path.write_text(json.dumps({"test": profile}), encoding="utf-8")
        return path

    def test_real_profiles_load(self):
        profiles = load_profiles(CONFIG_DIR / "profiles.json")
        self.assertEqual(set(profiles), {"budget", "business", "flexible"})
        budget = profiles["budget"]
        self.assertEqual(budget.destination_id, "MAL")
        self.assertEqual(budget.earliest_date, date(2026, 7, 12))
        self.assertEqual(budget.preferred_departure_from, time(7, 0))
        self.assertEqual(profiles["business"].min_change_level, "free")
        self.assertEqual(profiles["flexible"].min_change_level, "fee")

    def test_valid_profile_loads(self):
        profiles = load_profiles(self.write_profile())
        self.assertEqual(profiles["test"].max_price_eur, 50)

    def test_bad_weights_name_the_profile(self):
        path = self.write_profile(weights={"price": 50, "duration": 40})
        with self.assertRaises(ConfigError) as context:
            load_profiles(path)
        self.assertIn("profile 'test'", context.exception.reason)
        self.assertIn("add up to 100", context.exception.reason)

    def test_misspelled_key_is_rejected(self):
        profile = copy.deepcopy(VALID_PROFILE)
        profile["max_prise_eur"] = profile.pop("max_price_eur")
        path = self.folder / "profiles.json"
        path.write_text(json.dumps({"test": profile}), encoding="utf-8")
        with self.assertRaises(ConfigError) as context:
            load_profiles(path)
        self.assertIn("max_prise_eur", context.exception.reason)

    def test_unknown_change_level_is_rejected(self):
        with self.assertRaises(ConfigError):
            load_profiles(self.write_profile(min_change_level="sometimes"))

    def test_dates_in_wrong_order_are_rejected(self):
        with self.assertRaises(ConfigError):
            load_profiles(self.write_profile(earliest_date="2026-07-14", latest_date="2026-07-12"))

    def test_descriptor_rules_apply_to_profiles(self):
        for field, bad in (("seats_needed", 0), ("max_price_eur", -5), ("max_transfers", 1.5)):
            with self.subTest(field=field):
                with self.assertRaises(ConfigError):
                    load_profiles(self.write_profile(**{field: bad}))

    def test_missing_file_and_invalid_json(self):
        with self.assertRaises(DataFileError):
            load_profiles(self.folder / "missing.json")
        broken = self.folder / "broken.json"
        broken.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_profiles(broken)


if __name__ == "__main__":
    unittest.main()
