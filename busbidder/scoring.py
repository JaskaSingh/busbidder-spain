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
