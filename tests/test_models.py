import unittest

from busbidder.errors import InvalidValueError
from busbidder.models import Company, Destination, FareConditions


class CompanyAndDestinationTests(unittest.TestCase):

    def test_company_keeps_its_values(self):
        company = Company("VER", "VerdeBus", "Environment-focused services")
        self.assertEqual(company.company_id, "VER")
        self.assertEqual(company.name, "VerdeBus")

    def test_destination_keeps_its_values(self):
        destination = Destination("MAL", "Malaga", 530, True)
        self.assertEqual(destination.distance_km, 530)
        self.assertTrue(destination.coastal)

    def test_destination_distance_must_be_positive(self):
        for bad in (0, -72):
            with self.subTest(distance=bad):
                with self.assertRaises(InvalidValueError):
                    Destination("TOL", "Toledo", bad, False)


class FareConditionsTests(unittest.TestCase):

    def test_valid_conditions_are_described(self):
        fare = FareConditions("flex", "free", True)
        self.assertEqual(fare.describe(), "free change, refundable")
        self.assertEqual(FareConditions("basic", "none", False).describe(), "no changes, non-refundable")

    def test_unknown_change_option_is_rejected(self):
        with self.assertRaises(InvalidValueError):
            FareConditions("standard", "maybe", False)

    def test_refundable_must_be_boolean(self):
        with self.assertRaises(InvalidValueError):
            FareConditions("standard", "fee", "yes")

    def test_copy_is_equal_but_separate(self):
        fare = FareConditions("standard", "fee", False)
        copy = fare.copy()
        self.assertEqual(copy, fare)
        self.assertIsNot(copy, fare)


if __name__ == "__main__":
    unittest.main()
