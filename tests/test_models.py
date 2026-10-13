import unittest
from datetime import date, datetime

from busbidder.errors import InvalidValueError
from busbidder.models import Company, Destination, FareConditions, Offer


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


def make_offer(**changes):
    """Build a valid offer. Tests pass only the value they want to change."""
    values = {
        "offer_id": "OFR-00001",
        "company": Company("NOC", "NocheVia", "Overnight services"),
        "destination": Destination("MAL", "Malaga", 530, True),
        "fare": FareConditions("standard", "fee", False),
        "departure": datetime(2026, 7, 12, 20, 30),
        "arrival": datetime(2026, 7, 13, 4, 35),
        "price_eur": 34.72,
        "transfers": 1,
        "luggage_kg": 20,
        "available_seats": 18,
        "rating": 3.8,
        "co2_kg": 13.2,
    }
    values.update(changes)
    return Offer(**values)


class OfferTests(unittest.TestCase):

    def test_overnight_offer_is_valid(self):
        offer = make_offer()
        self.assertEqual(offer.duration_minutes, 8 * 60 + 5)
        self.assertEqual(offer.travel_date, date(2026, 7, 12))

    def test_offer_is_composed_of_other_objects(self):
        offer = make_offer()
        self.assertEqual(offer.company.name, "NocheVia")
        self.assertEqual(offer.destination.name, "Malaga")
        self.assertEqual(offer.fare.describe(), "change for a fee, non-refundable")

    def test_arrival_before_or_at_departure_is_rejected(self):
        for arrival in (datetime(2026, 7, 12, 19, 0), datetime(2026, 7, 12, 20, 30)):
            with self.subTest(arrival=arrival):
                with self.assertRaises(InvalidValueError) as context:
                    make_offer(arrival=arrival)
                self.assertEqual(context.exception.field, "arrival")

    def test_descriptor_rules_apply_to_offer_fields(self):
        cases = {
            "price_eur": -12.5,
            "transfers": -1,
            "available_seats": 2.5,
            "rating": 6.0,
            "co2_kg": -1,
        }
        for field, bad in cases.items():
            with self.subTest(field=field):
                with self.assertRaises(InvalidValueError) as context:
                    make_offer(**{field: bad})
                self.assertEqual(context.exception.field, field)

    def test_sold_out_offer_is_still_valid(self):
        self.assertEqual(make_offer(available_seats=0).available_seats, 0)

    def test_missing_emissions_are_allowed(self):
        self.assertIsNone(make_offer(co2_kg=None).co2_kg)


if __name__ == "__main__":
    unittest.main()
