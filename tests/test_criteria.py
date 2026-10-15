import unittest
from datetime import datetime, time, timedelta

from busbidder.criteria import (
    CRITERIA,
    available_criteria,
    criterion,
    departure_time_score,
    duration_score,
    flexibility_score,
    get_criterion,
    minutes_outside_window,
    price_score,
)
from busbidder.errors import RegistryError
from busbidder.models import FareConditions
from tests.test_filtering import make_profile
from tests.test_models import make_offer


class RegistryTests(unittest.TestCase):

    def test_four_required_criteria_are_registered(self):
        self.assertEqual(
            available_criteria(), ["departure_time", "duration", "flexibility", "price"]
        )

    def test_lookup_by_name_returns_the_function(self):
        self.assertIs(get_criterion("price"), price_score)

    def test_unknown_name_gives_meaningful_error(self):
        with self.assertRaises(RegistryError) as context:
            get_criterion("comfort")
        self.assertIn("available: departure_time", context.exception.reason)

    def test_duplicate_name_is_refused(self):
        with self.assertRaises(RegistryError):
            @criterion("price")
            def another_price(offer, profile):
                return 0

    def test_decorator_returns_original_function_and_new_criterion_works(self):
        try:
            @criterion("test_rating")
            def rating_score(offer, profile):
                return (offer.rating - 1) / 4 * 100

            self.assertEqual(rating_score.__name__, "rating_score")
            self.assertEqual(get_criterion("test_rating")(make_offer(rating=5), None), 100)
        finally:
            CRITERIA.pop("test_rating", None)


class PriceTests(unittest.TestCase):

    def test_price_scores(self):
        profile = make_profile(max_price_eur=50)
        self.assertEqual(price_score(make_offer(price_eur=0), profile), 100)
        self.assertEqual(price_score(make_offer(price_eur=25), profile), 50)
        self.assertEqual(price_score(make_offer(price_eur=50), profile), 0)

    def test_price_above_budget_is_clamped_to_zero(self):
        self.assertEqual(price_score(make_offer(price_eur=80), make_profile(max_price_eur=50)), 0)


class DurationTests(unittest.TestCase):
    # Malaga is 530 km. At 95 km/h the fastest plausible time is about 335 minutes.

    def test_faster_is_better_and_scores_stay_in_range(self):
        profile = make_profile()

        def offer_taking(minutes):
            start = datetime(2026, 7, 13, 8, 0)
            return make_offer(departure=start, arrival=start + timedelta(minutes=minutes))

        fast, slow = offer_taking(340), offer_taking(600)
        self.assertGreater(duration_score(fast, profile), duration_score(slow, profile))
        for offer in (offer_taking(200), offer_taking(900)):
            self.assertTrue(0 <= duration_score(offer, profile) <= 100)

    def test_traveller_maximum_scores_zero(self):
        offer = make_offer()  # 485 minutes
        self.assertEqual(duration_score(offer, make_profile(max_duration_minutes=485)), 0)


class DepartureTimeTests(unittest.TestCase):

    def test_inside_window_and_edges_score_100(self):
        for hour in (7, 9, 11):
            self.assertEqual(minutes_outside_window(time(hour, 0), time(7, 0), time(11, 0)), 0)

    def test_distance_is_measured_around_the_clock(self):
        self.assertEqual(minutes_outside_window(time(23, 0), time(1, 0), time(5, 0)), 120)

    def test_window_crossing_midnight(self):
        self.assertEqual(minutes_outside_window(time(0, 30), time(22, 0), time(2, 0)), 0)
        self.assertEqual(minutes_outside_window(time(4, 0), time(22, 0), time(2, 0)), 120)

    def test_score_falls_25_per_hour_and_stops_at_zero(self):
        profile = make_profile()  # window 07:00 to 11:00
        def at(hour, minute=0):
            start = datetime(2026, 7, 13, hour, minute)
            return make_offer(departure=start, arrival=datetime(2026, 7, 14, 6, 0))
        self.assertEqual(departure_time_score(at(12), profile), 75)
        self.assertEqual(departure_time_score(at(13, 30), profile), 37.5)
        self.assertEqual(departure_time_score(at(20), profile), 0)


class FlexibilityTests(unittest.TestCase):

    def test_flexibility_levels(self):
        cases = [
            ("none", False, 0), ("fee", False, 50), ("free", False, 75),
            ("fee", True, 75), ("free", True, 100),
        ]
        for changeable, refundable, expected in cases:
            offer = make_offer(fare=FareConditions("standard", changeable, refundable))
            with self.subTest(changeable=changeable, refundable=refundable):
                self.assertEqual(flexibility_score(offer, make_profile()), expected)


if __name__ == "__main__":
    unittest.main()
