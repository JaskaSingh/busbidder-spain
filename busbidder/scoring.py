"""Normalisation strategies and ranking.

A normalisation strategy takes the scores of one criterion across all
accepted offers and returns them on the 0 to 100 scale used for weighting.
Strategies are registered by name, so the same ranking code can run with
either one selected from the command line or an experiment.

- anchored: keeps the criterion scores as they are. They are already on a
  fixed 0 to 100 scale anchored to the traveller's budget, the route's
  reference time and so on, so an offer's score never depends on which
  other offers are in the list.
- minmax: rescales so the worst offer in the list gets 0 and the best gets
  100. Uses the full scale, but an offer's score changes when other offers
  are added or removed, which can reverse the order of two offers.
"""

from dataclasses import dataclass

from .criteria import get_criterion
from .registry import Registry

STRATEGIES = Registry("normalisation strategy")
strategy = STRATEGIES.register

DEFAULT_STRATEGY = "anchored"


@strategy("anchored")
def anchored(scores):
    return list(scores)


@strategy("minmax")
def minmax(scores):
    """Rescale to 0 to 100 within this list.

    If every score is equal (including a single offer), the criterion cannot
    tell the offers apart. All of them get 100, because each one equals the
    best value seen, and the criterion has no effect on the order. This also
    avoids dividing by zero.
    """
    scores = list(scores)
    if not scores:
        return []
    low, high = min(scores), max(scores)
    if high == low:
        return [100.0] * len(scores)
    return [100 * (score - low) / (high - low) for score in scores]


def get_strategy(name):
    return STRATEGIES.get(name)


# Two totals closer than this are reported as a close call.
CLOSE_MARGIN_POINTS = 1.0

# Totals are rounded to this many decimals before comparing, so tiny float
# differences (such as 0.1 + 0.2) cannot decide the order.
TOTAL_DECIMALS = 6


@dataclass
class ScoredOffer:
    """One offer with its criterion scores, weighted contributions and total."""

    offer: object
    scores: dict          # criterion name -> normalised score 0 to 100
    contributions: dict   # criterion name -> points added to the total
    total: float
    rank: int = 0


def tie_break_key(scored):
    """Sort order: highest total, then lowest price, earliest departure, offer ID.

    Company name is deliberately not used, because it would always favour
    the same company when totals are equal.
    """
    offer = scored.offer
    return (-round(scored.total, TOTAL_DECIMALS), offer.price_eur, offer.departure, offer.offer_id)


def rank_offers(offers, profile, strategy_name=DEFAULT_STRATEGY):
    """Score and rank offers that have already passed the hard constraints.

    Each criterion named in the profile's weights is scored for every offer,
    normalised across the list with the chosen strategy, and multiplied by
    its weight. Weights are whole percentages, so the total is also 0 to 100.
    """
    offers = list(offers)
    if not offers:
        return []
    normalise = get_strategy(strategy_name)

    normalised = {}
    for name in profile.weights:
        score = get_criterion(name)
        normalised[name] = normalise([score(offer, profile) for offer in offers])

    ranking = []
    for index, offer in enumerate(offers):
        scores = {name: normalised[name][index] for name in profile.weights}
        contributions = {
            name: profile.weights[name] * scores[name] / 100 for name in profile.weights
        }
        ranking.append(ScoredOffer(offer, scores, contributions, sum(contributions.values())))

    ranking.sort(key=tie_break_key)
    for position, scored in enumerate(ranking, start=1):
        scored.rank = position
    return ranking


def is_close_call(ranking):
    """True if the first two offers are within CLOSE_MARGIN_POINTS of each other."""
    if len(ranking) < 2:
        return False
    return ranking[0].total - ranking[1].total < CLOSE_MARGIN_POINTS
