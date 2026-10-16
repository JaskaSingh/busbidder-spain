import unittest
from datetime import datetime, timedelta

from busbidder.criteria import CRITERIA, criterion
from busbidder.errors import RegistryError
from busbidder.models import FareConditions
from busbidder.scoring import (
    STRATEGIES,
    anchored,
    get_strategy,
    is_close_call,
    minmax,
    rank_offers,
)
from tests.test_filtering import make_profile
from tests.test_models import make_offer


def offer_at(offer_id, price, hour, minutes, changeable="fee", refundable=False):
    """A Malaga offer leaving 13 July at the given hour and taking the given minutes."""
    departure = datetime(2026, 7, 13, hour, 0)
    return make_offer(
        offer_id=offer_id,
        price_eur=price,
        departure=departure,
        arrival=departure + timedelta(minutes=minutes),
        fare=FareConditions("standard", changeable, refundable),
    )


class StrategyRegistryTests(unittest.TestCase):

    def test_both_strategies_are_registered(self):
        self.assertEqual(STRATEGIES.names(), ["anchored", "minmax"])
        self.assertIs(get_strategy("minmax"), minmax)

    def test_unknown_strategy_gives_meaningful_error(self):
        with self.assertRaises(RegistryError) as context:
            get_strategy("zscore")
        self.assertIn("not a known normalisation strategy", context.exception.reason)
        self.assertIn("anchored, minmax", context.exception.reason)

    def test_duplicate_strategy_is_refused(self):
        with self.assertRaises(RegistryError):
            @STRATEGIES.register("anchored")
            def another(scores):
                return scores


class AnchoredTests(unittest.TestCase):

    def test_scores_are_unchanged(self):
        self.assertEqual(anchored([12.5, 80, 100]), [12.5, 80, 100])


class MinMaxTests(unittest.TestCase):

    def test_worst_gets_0_and_best_gets_100(self):
        self.assertEqual(minmax([10, 20, 30]), [0, 50, 100])

    def test_equal_values_do_not_divide_by_zero(self):
        self.assertEqual(minmax([40, 40, 40]), [100, 100, 100])

    def test_single_offer_and_empty_list(self):
        self.assertEqual(minmax([40]), [100])
        self.assertEqual(minmax([]), [])

    def test_score_depends_on_the_other_offers(self):
        # The same offer (score 40) is best in one list and in the middle of
        # another. This is the property that can cause rank reversal.
        self.assertEqual(minmax([20, 40])[1], 100)
        self.assertEqual(minmax([20, 40, 60])[1], 50)

    def test_anchored_score_does_not_depend_on_other_offers(self):
        self.assertEqual(anchored([20, 40])[1], anchored([20, 40, 60])[1])


class RankingTests(unittest.TestCase):

    def setUp(self):
        # Budget 50, window 07:00 to 11:00, weights 40/25/15/20.
        self.profile = make_profile()

    def test_hand_calculated_ranking(self):
        # Price 25 of 50 gives 50 points. 335 minutes is the fastest plausible
        # time for 530 km at 95 km/h, so duration is 100. 08:00 is inside the
        # window, so departure time is 100. Fee change gives 50.
        # Total = 0.40*50 + 0.25*100 + 0.15*100 + 0.20*50 = 70.
        ranking = rank_offers([offer_at("OFR-00001", 25, 8, 335)], self.profile)
        top = ranking[0]
        self.assertAlmostEqual(top.scores["price"], 50)
        self.assertAlmostEqual(top.scores["duration"], 100, delta=0.5)
        self.assertEqual(top.scores["departure_time"], 100)
        self.assertEqual(top.scores["flexibility"], 50)
        self.assertAlmostEqual(top.total, 70, delta=0.2)

    def test_contributions_add_up_to_total(self):
        ranking = rank_offers(
            [offer_at("OFR-00001", 30, 9, 400), offer_at("OFR-00002", 45, 15, 380, "free", True)],
            self.profile,
        )
        for scored in ranking:
            self.assertAlmostEqual(sum(scored.contributions.values()), scored.total)

    def test_higher_total_ranks_first_and_ranks_are_numbered(self):
        cheap = offer_at("OFR-00001", 20, 9, 400)
        dear = offer_at("OFR-00002", 48, 9, 400)
        ranking = rank_offers([dear, cheap], self.profile)
        self.assertEqual([s.offer for s in ranking], [cheap, dear])
        self.assertEqual([s.rank for s in ranking], [1, 2])

    def test_equal_totals_break_by_departure_then_offer_id(self):
        # Identical offers apart from ID and an equally convenient departure.
        early = offer_at("OFR-00009", 30, 8, 400)
        late = offer_at("OFR-00001", 30, 10, 400)
        same_time = offer_at("OFR-00005", 30, 8, 400)
        ranking = rank_offers([late, early, same_time], self.profile)
        self.assertEqual(
            [s.offer.offer_id for s in ranking], ["OFR-00005", "OFR-00009", "OFR-00001"]
        )
        self.assertTrue(is_close_call(ranking))

    def test_zero_weight_has_no_effect(self):
        profile = make_profile(weights={"price": 100, "duration": 0, "departure_time": 0, "flexibility": 0})
        slow_cheap = offer_at("OFR-00001", 20, 3, 900)
        fast_dear = offer_at("OFR-00002", 40, 9, 340, "free", True)
        ranking = rank_offers([fast_dear, slow_cheap], profile)
        self.assertIs(ranking[0].offer, slow_cheap)

    def test_empty_and_single_offer(self):
        self.assertEqual(rank_offers([], self.profile), [])
        ranking = rank_offers([offer_at("OFR-00001", 30, 9, 400)], self.profile)
        self.assertEqual(len(ranking), 1)
        self.assertFalse(is_close_call(ranking))

    def test_minmax_strategy_can_be_selected_by_name(self):
        offers = [offer_at("OFR-00001", 20, 9, 400), offer_at("OFR-00002", 40, 9, 400)]
        ranking = rank_offers(offers, self.profile, "minmax")
        self.assertEqual(ranking[0].scores["price"], 100)
        self.assertEqual(ranking[1].scores["price"], 0)

    def test_unknown_strategy_is_refused(self):
        with self.assertRaises(RegistryError):
            rank_offers([offer_at("OFR-00001", 20, 9, 400)], self.profile, "zscore")

    def test_new_criterion_works_without_changing_the_ranking_code(self):
        try:
            @criterion("test_rating")
            def rating_score(offer, profile):
                return (offer.rating - 1) / 4 * 100

            profile = make_profile(weights={"price": 50, "test_rating": 50})
            low = make_offer(offer_id="OFR-00001", price_eur=30, rating=2.0)
            high = make_offer(offer_id="OFR-00002", price_eur=30, rating=4.8)
            ranking = rank_offers([low, high], profile)
            self.assertIs(ranking[0].offer, high)
            self.assertIn("test_rating", ranking[0].contributions)
        finally:
            CRITERIA.remove("test_rating")


if __name__ == "__main__":
    unittest.main()
