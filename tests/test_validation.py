import unittest

from busbidder.errors import InvalidValueError
from busbidder.validation import Bounded


class Sample:
    """Small class used only to test the descriptor."""

    rating = Bounded(minimum=1, maximum=5)
    price = Bounded(minimum=0)
    seats = Bounded(minimum=0, whole_number=True)
    co2 = Bounded(minimum=0, optional=True)

    def __init__(self, rating=3, price=10, seats=5, co2=None):
        self.rating = rating
        self.price = price
        self.seats = seats
        self.co2 = co2


class BoundedTests(unittest.TestCase):

    def test_valid_values_are_stored_and_returned(self):
        sample = Sample(rating=4, price=25.5)
        self.assertEqual(sample.rating, 4)
        self.assertEqual(sample.price, 25.5)

    def test_value_is_stored_under_private_name(self):
        sample = Sample()
        self.assertIn("_rating", vars(sample))
        self.assertNotIn("rating", vars(sample))

    def test_both_boundaries_are_accepted(self):
        self.assertEqual(Sample(rating=1).rating, 1)
        self.assertEqual(Sample(rating=5).rating, 5)
        self.assertEqual(Sample(price=0).price, 0)

    def test_values_outside_range_are_rejected(self):
        for bad in (0, 0.99, 5.01, 6):
            with self.subTest(rating=bad):
                with self.assertRaises(InvalidValueError):
                    Sample(rating=bad)

    def test_negative_price_is_rejected(self):
        with self.assertRaises(InvalidValueError):
            Sample(price=-0.01)

    def test_wrong_types_are_rejected(self):
        for bad in ("4", None, True, [4]):
            with self.subTest(rating=bad):
                with self.assertRaises(InvalidValueError):
                    Sample(rating=bad)

    def test_nan_and_infinity_are_rejected(self):
        for bad in (float("nan"), float("inf")):
            with self.subTest(price=bad):
                with self.assertRaises(InvalidValueError):
                    Sample(price=bad)

    def test_error_carries_field_value_and_reason(self):
        with self.assertRaises(InvalidValueError) as context:
            Sample(rating=7)
        error = context.exception
        self.assertEqual(error.field, "rating")
        self.assertEqual(error.value, 7)
        self.assertEqual(error.reason, "must be at most 5")

    def test_rejected_assignment_keeps_old_value(self):
        sample = Sample(rating=3)
        with self.assertRaises(InvalidValueError):
            sample.rating = 9
        self.assertEqual(sample.rating, 3)

    def test_whole_number_rejects_floats(self):
        self.assertEqual(Sample(seats=0).seats, 0)
        with self.assertRaises(InvalidValueError):
            Sample(seats=2.5)

    def test_optional_accepts_none_but_still_checks_numbers(self):
        self.assertIsNone(Sample(co2=None).co2)
        self.assertEqual(Sample(co2=6.4).co2, 6.4)
        with self.assertRaises(InvalidValueError):
            Sample(co2=-1)

    def test_none_is_rejected_when_not_optional(self):
        with self.assertRaises(InvalidValueError):
            Sample(price=None)

    def test_minimum_above_maximum_is_refused(self):
        with self.assertRaises(ValueError):
            Bounded(minimum=5, maximum=1)


if __name__ == "__main__":
    unittest.main()
