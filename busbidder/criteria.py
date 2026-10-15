"""Scoring criteria, registered by name with a decorator.

Each criterion is a function score(offer, profile) that returns a score from
0 to 100, where higher is always better. The @criterion("name") decorator
stores the function in CRITERIA under that name. Profile weights refer to
criteria by these names, so adding a new criterion only needs one decorated
function and no change to the ranking code.

The scores here are anchored to fixed reference points (the traveller's
budget, the route's fastest plausible time), so an offer's score does not
depend on which other offers are in the list.
"""

from .errors import RegistryError

CRITERIA = {}


def criterion(name):
    """Decorator factory: register the decorated function under the given name."""

    def register(function):
        if name in CRITERIA:
            raise RegistryError(name, "is already registered as a criterion")
        function.criterion_name = name
        CRITERIA[name] = function
        return function

    return register


def get_criterion(name):
    try:
        return CRITERIA[name]
    except KeyError:
        available = ", ".join(available_criteria())
        raise RegistryError(name, f"is not a known criterion (available: {available})") from None


def available_criteria():
    return sorted(CRITERIA)


def clamp(score):
    """Keep a score between 0 and 100. This also handles extreme values."""
    return max(0.0, min(100.0, score))


# Reference speed for the fastest plausible bus on a route. A journey at this
# average speed scores 100 on duration.
REFERENCE_SPEED_KMH = 95

# Departure convenience loses this many points per hour outside the window.
POINTS_LOST_PER_HOUR = 25

FLEXIBILITY_POINTS = {"none": 0, "fee": 50, "free": 75}
REFUNDABLE_BONUS = 25


@criterion("price")
def price_score(offer, profile):
    """100 for a free ticket, 0 at the traveller's budget, linear between."""
    budget = profile.max_price_eur
    if budget == 0:
        return 100.0 if offer.price_eur == 0 else 0.0
    return clamp(100 * (budget - offer.price_eur) / budget)


@criterion("duration")
def duration_score(offer, profile):
    """100 at the fastest plausible time for the route, 0 at the slowest acceptable.

    The slowest acceptable time is the traveller's maximum duration if they
    set one, otherwise twice the fastest plausible time.
    """
    fastest = offer.destination.distance_km / REFERENCE_SPEED_KMH * 60
    slowest = profile.max_duration_minutes or 2 * fastest
    if slowest <= fastest:
        return 100.0 if offer.duration_minutes <= fastest else 0.0
    return clamp(100 * (slowest - offer.duration_minutes) / (slowest - fastest))


def minutes_outside_window(departure_time, window_from, window_to):
    """How many minutes a departure lies outside a daily window.

    Distances are measured around the clock, so 23:00 is two hours from a
    window starting at 01:00. Windows that cross midnight (22:00 to 02:00)
    are supported.
    """
    def minutes(t):
        return t.hour * 60 + t.minute

    dep, start, end = minutes(departure_time), minutes(window_from), minutes(window_to)
    if start <= end:
        inside = start <= dep <= end
    else:
        inside = dep >= start or dep <= end
    if inside:
        return 0

    def around_clock(a, b):
        difference = abs(a - b) % (24 * 60)
        return min(difference, 24 * 60 - difference)

    return min(around_clock(dep, start), around_clock(dep, end))


@criterion("departure_time")
def departure_time_score(offer, profile):
    """100 inside the preferred window, minus 25 points per hour outside it."""
    outside = minutes_outside_window(
        offer.departure.time(),
        profile.preferred_departure_from,
        profile.preferred_departure_to,
    )
    return clamp(100 - POINTS_LOST_PER_HOUR * outside / 60)


@criterion("flexibility")
def flexibility_score(offer, profile):
    """No changes 0, change for a fee 50, free change 75, plus 25 if refundable."""
    points = FLEXIBILITY_POINTS[offer.fare.changeable]
    if offer.fare.refundable:
        points += REFUNDABLE_BONUS
    return clamp(points)
