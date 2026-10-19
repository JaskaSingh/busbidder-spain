import unittest

from busbidder.explain import explain_top, format_minutes
from busbidder.models import FareConditions
from busbidder.scoring import rank_offers
from tests.test_filtering import make_profile
from tests.test_scoring import offer_at


class FormatTests(unittest.TestCase):

    def test_minutes_are_formatted_as_hours_and_minutes(self):
        self.assertEqual(format_minutes(485), "8 h 05 min")
        self.assertEqual(format_minutes(30), "0 h 30 min")


class ExplanationTests(unittest.TestCase):

    def setUp(self):
        self.profile = make_profile()  # budget 50, window 07:00 to 11:00, weights 40/25/15/20

    def explain(self, offers, profile=None):
        profile = profile or self.profile
        return explain_top(rank_offers(offers, profile), profile)

    def test_empty_ranking_gives_no_explanation(self):
        self.assertIsNone(explain_top([], self.profile))

    def test_wording_never_claims_best(self):
        text = self.explain([offer_at("OFR-00001", 20, 9, 400), offer_at("OFR-00002", 45, 9, 400)]).text()
        self.assertIn("ranked first under your preferences", text)
        self.assertNotIn("best", text.lower())

    def test_cheap_winner_names_price_as_advantage(self):
        cheap = offer_at("OFR-00001", 10, 9, 400)
        dear = offer_at("OFR-00002", 45, 9, 400)
        explanation = self.explain([cheap, dear])
        self.assertTrue(any("EUR 10.00" in line for line in explanation.advantages))

    def test_a_disadvantage_is_always_named(self):
        # The winner is better or equal on everything, so its weakest point is shown.
        winner = offer_at("OFR-00001", 10, 9, 340, "free", True)
        loser = offer_at("OFR-00002", 45, 15, 600, "none")
        explanation = self.explain([winner, loser])
        self.assertEqual(len(explanation.disadvantages), 1)

    def test_departure_outside_window_is_shown_as_a_disadvantage(self):
        late_but_cheap = offer_at("OFR-00001", 5, 14, 400)
        early_but_dear = offer_at("OFR-00002", 49, 8, 400)
        explanation = self.explain([late_but_cheap, early_but_dear])
        self.assertTrue(any("outside your preferred window" in line for line in explanation.disadvantages))

    def test_close_call_is_reported(self):
        a = offer_at("OFR-00001", 30, 9, 400)
        b = offer_at("OFR-00002", 30.2, 9, 400)
        self.assertIn("Close call", self.explain([a, b]).margin_note)

    def test_clear_lead_is_reported_without_close_call(self):
        a = offer_at("OFR-00001", 10, 9, 400, "free", True)
        b = offer_at("OFR-00002", 48, 16, 600, "none")
        note = self.explain([a, b]).margin_note
        self.assertNotIn("Close call", note)
        self.assertIn("points ahead of", note)

    def test_single_offer_is_explained_as_the_only_option(self):
        explanation = self.explain([offer_at("OFR-00001", 30, 9, 400)])
        self.assertIn("only offer", explanation.advantages[0])
        self.assertEqual(len(explanation.disadvantages), 1)

    def test_zero_weight_criteria_are_not_mentioned(self):
        profile = make_profile(weights={"price": 100, "duration": 0, "departure_time": 0, "flexibility": 0})
        explanation = self.explain(
            [offer_at("OFR-00001", 10, 3, 900), offer_at("OFR-00002", 45, 9, 340, "free", True)], profile
        )
        text = explanation.text()
        self.assertNotIn("departure time", text)
        self.assertNotIn("flexibility", text)


if __name__ == "__main__":
    unittest.main()
