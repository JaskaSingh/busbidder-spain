import unittest

from busbidder.errors import RegistryError
from busbidder.scoring import STRATEGIES, anchored, get_strategy, minmax


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


if __name__ == "__main__":
    unittest.main()
