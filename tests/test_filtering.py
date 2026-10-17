import unittest
from datetime import date, datetime

from busbidder.filtering import (
    BudgetConstraint,
    ChangeLevelConstraint,
    DateWindowConstraint,
    DestinationConstraint,
    MaxDurationConstraint,
    SeatsConstraint,
    TransfersConstraint,
    constraints_for,
    filter_offers,
)
from busbidder.models import FareConditions
from busbidder.profiles import TravellerProfile
from tests.test_models import make_offer


def make_profile(**changes):
    values = {
        "name": "test",
        "label": "Test traveller",
        "destination_id": "MAL",
        "earliest_date": date(2026, 7, 12),
        "latest_date": date(2026, 7, 14),
        "max_price_eur": 50,
        "seats_needed": 1,
        "max_transfers": 1,
        "min_change_level": "none",
        "max_duration_minutes": None,
        "preferred_departure_from": datetime(2026, 1, 1, 7).time(),
        "preferred_departure_to": datetime(2026, 1, 1, 11).time(),
        "weights": {"price": 40, "duration": 25, "departure_time": 15, "flexibility": 20},
    }
    values.update(changes)
    return TravellerProfile(**values)


class ConstraintBoundaryTests(unittest.TestCase):

    def test_price_exactly_at_budget_is_kept_one_cent_over_is_removed(self):
        rule = BudgetConstraint(50)
        self.assertIsNone(rule.check(make_offer(price_eur=50.00)))
        self.assertIsNotNone(rule.check(make_offer(price_eur=50.01)))

    def test_transfers_exactly_at_maximum_are_kept(self):
        rule = TransfersConstraint(1)
        self.assertIsNone(rule.check(make_offer(transfers=1)))
        self.assertIsNotNone(rule.check(make_offer(transfers=2)))

    def test_seats_exactly_enough_are_kept(self):
        rule = SeatsConstraint(2)
        self.assertIsNone(rule.check(make_offer(available_seats=2)))
        self.assertIsNotNone(rule.check(make_offer(available_seats=1)))

    def test_sold_out_offer_is_removed_by_seats(self):
        self.assertIsNotNone(SeatsConstraint(1).check(make_offer(available_seats=0)))

    def test_date_window_includes_both_ends(self):
        rule = DateWindowConstraint(date(2026, 7, 12), date(2026, 7, 14))
        for day, inside in ((11, False), (12, True), (14, True), (15, False)):
            offer = make_offer(
                departure=datetime(2026, 7, day, 10, 0),
                arrival=datetime(2026, 7, day, 18, 0),
            )
            with self.subTest(day=day):
                self.assertEqual(rule.check(offer) is None, inside)

    def test_overnight_offer_counts_by_departure_date(self):
        rule = DateWindowConstraint(date(2026, 7, 12), date(2026, 7, 14))
        offer = make_offer(departure=datetime(2026, 7, 14, 23, 30), arrival=datetime(2026, 7, 15, 7, 35))
        self.assertIsNone(rule.check(offer))

    def test_change_level_fee_accepts_fee_and_free(self):
        rule = ChangeLevelConstraint("fee")
        for option, passes in (("none", False), ("fee", True), ("free", True)):
            offer = make_offer(fare=FareConditions("standard", option, False))
            with self.subTest(changeable=option):
                self.assertEqual(rule.check(offer) is None, passes)

    def test_change_level_free_accepts_only_free(self):
        rule = ChangeLevelConstraint("free")
        for option, passes in (("none", False), ("fee", False), ("free", True)):
            offer = make_offer(fare=FareConditions("standard", option, False))
            with self.subTest(changeable=option):
                self.assertEqual(rule.check(offer) is None, passes)

    def test_duration_exactly_at_maximum_is_kept(self):
        offer = make_offer()  # 485 minutes
        self.assertIsNone(MaxDurationConstraint(485).check(offer))
        self.assertIsNotNone(MaxDurationConstraint(484).check(offer))

    def test_wrong_destination_is_reported(self):
        self.assertIn("not BAR", DestinationConstraint("BAR").check(make_offer()))


class ConstraintsForProfileTests(unittest.TestCase):

    def test_optional_constraints_only_when_requested(self):
        names = {rule.name for rule in constraints_for(make_profile())}
        self.assertNotIn("change level", names)
        self.assertNotIn("duration", names)

        strict = make_profile(min_change_level="free", max_duration_minutes=480)
        names = {rule.name for rule in constraints_for(strict)}
        self.assertIn("change level", names)
        self.assertIn("duration", names)


class FilterOffersTests(unittest.TestCase):

    def setUp(self):
        on_route = dict(departure=datetime(2026, 7, 13, 10, 0), arrival=datetime(2026, 7, 13, 17, 0))
        self.good = make_offer(offer_id="OFR-00001", price_eur=40, **on_route)
        self.expensive = make_offer(offer_id="OFR-00002", price_eur=60, **on_route)
        self.expensive_and_full = make_offer(
            offer_id="OFR-00003", price_eur=60, available_seats=0, **on_route
        )
        self.other_day = make_offer(
            offer_id="OFR-00004",
            departure=datetime(2026, 7, 20, 10, 0),
            arrival=datetime(2026, 7, 20, 17, 0),
        )
        offers = [self.good, self.expensive, self.expensive_and_full, self.other_day]
        self.result = filter_offers(offers, constraints_for(make_profile()))

    def test_offers_are_split_correctly(self):
        self.assertEqual(self.result.accepted, [self.good])
        self.assertEqual(self.result.out_of_scope, 1)
        self.assertEqual(self.result.in_scope, 3)

    def test_every_failed_constraint_is_recorded(self):
        removal = next(r for r in self.result.removed if r.offer is self.expensive_and_full)
        self.assertEqual({name for name, _ in removal.failures}, {"budget", "seats"})

    def test_counts_and_summary(self):
        self.assertEqual(self.result.counts_by_constraint(), {"budget": 2, "seats": 1})
        self.assertIn("Removed 2 (2 budget, 1 seats)", self.result.summary())

    def test_all_offers_removed_gives_empty_accepted_list(self):
        result = filter_offers([self.expensive], constraints_for(make_profile(max_price_eur=10)))
        self.assertEqual(result.accepted, [])
        self.assertEqual(len(result.removed), 1)


if __name__ == "__main__":
    unittest.main()
