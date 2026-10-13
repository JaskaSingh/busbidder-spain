import unittest
from datetime import date, time

from busbidder.errors import InvalidValueError
from busbidder.validation import (
    OFFER_ID_PATTERN,
    clean_code,
    parse_choice,
    parse_date,
    parse_time,
    parse_yes_no,
    require_text,
    to_float,
    to_int,
    to_optional_float,
    validate_identifier,
)


class IdentifierTests(unittest.TestCase):

    def test_valid_offer_id_is_accepted(self):
        self.assertEqual(validate_identifier("offer_id", "OFR-00042", OFFER_ID_PATTERN), "OFR-00042")

    def test_malformed_offer_ids_are_rejected(self):
        for bad in ("OFR-12", "OFR-123456", "ofr-00042", "XOFR-00042", "OFR-00042X"):
            with self.subTest(offer_id=bad):
                with self.assertRaises(InvalidValueError):
                    validate_identifier("offer_id", bad, OFFER_ID_PATTERN)

    def test_code_is_cleaned_to_upper_case(self):
        self.assertEqual(clean_code("destination_id", " mal "), "MAL")

    def test_code_with_wrong_length_or_digits_is_rejected(self):
        for bad in ("MA", "MALA", "M4L"):
            with self.subTest(code=bad):
                with self.assertRaises(InvalidValueError):
                    clean_code("destination_id", bad)


class NumberTests(unittest.TestCase):

    def test_numbers_are_converted(self):
        self.assertEqual(to_int("transfers", " 2 "), 2)
        self.assertEqual(to_float("price_eur", "45.02"), 45.02)

    def test_text_is_not_a_number(self):
        with self.assertRaises(InvalidValueError):
            to_float("price_eur", "abc")
        with self.assertRaises(InvalidValueError):
            to_int("available_seats", "3.5")

    def test_missing_value_is_reported_as_missing(self):
        with self.assertRaises(InvalidValueError) as context:
            to_float("price_eur", "")
        self.assertEqual(context.exception.reason, "is missing")

    def test_optional_value_can_be_empty(self):
        self.assertIsNone(to_optional_float("co2_kg", ""))
        self.assertEqual(to_optional_float("co2_kg", "6.4"), 6.4)


class DateTimeTests(unittest.TestCase):

    def test_valid_date_and_time(self):
        self.assertEqual(parse_date("departure_date", "2026-07-13"), date(2026, 7, 13))
        self.assertEqual(parse_time("departure_time", "23:45"), time(23, 45))

    def test_impossible_dates_are_rejected(self):
        for bad in ("2026-02-30", "2026-13-01", "13.07.2026", "2026/07/13"):
            with self.subTest(date=bad):
                with self.assertRaises(InvalidValueError):
                    parse_date("departure_date", bad)

    def test_leap_day_only_in_leap_years(self):
        self.assertEqual(parse_date("departure_date", "2028-02-29"), date(2028, 2, 29))
        with self.assertRaises(InvalidValueError):
            parse_date("departure_date", "2026-02-29")

    def test_impossible_times_are_rejected(self):
        for bad in ("25:10", "12:60", "noon"):
            with self.subTest(time=bad):
                with self.assertRaises(InvalidValueError):
                    parse_time("departure_time", bad)

    def test_time_boundaries_are_accepted(self):
        self.assertEqual(parse_time("departure_time", "00:00"), time(0, 0))
        self.assertEqual(parse_time("departure_time", "23:59"), time(23, 59))


class ChoiceTests(unittest.TestCase):

    def test_allowed_choice_is_returned(self):
        self.assertEqual(parse_choice("changeable", "fee", {"none", "fee", "free"}), "fee")

    def test_unknown_choice_lists_the_options(self):
        with self.assertRaises(InvalidValueError) as context:
            parse_choice("changeable", "maybe", {"none", "fee", "free"})
        self.assertIn("fee, free, none", context.exception.reason)

    def test_yes_no_becomes_boolean(self):
        self.assertTrue(parse_yes_no("refundable", "yes"))
        self.assertFalse(parse_yes_no("refundable", "no"))
        with self.assertRaises(InvalidValueError):
            parse_yes_no("refundable", "perhaps")

    def test_require_text_strips_spaces(self):
        self.assertEqual(require_text("name", "  Malaga "), "Malaga")


if __name__ == "__main__":
    unittest.main()
