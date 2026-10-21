"""Hard constraints that remove unacceptable offers before ranking.

Each constraint is a small class with a check(offer) method that returns
None when the offer is acceptable, or a short reason when it is not. The
constraints for a traveller are built from their profile, so the same
attribute can be a hard rule for one traveller and absent for another.

Destination and date window are scope constraints: they decide which offers
are relevant at all. Offers outside the scope are only counted, not listed,
so the removal summary is about relevant offers the traveller would care
about.
"""

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field

from .models import CHANGE_OPTIONS


class Constraint(ABC):
    """Base class for all hard constraints."""

    name = "constraint"
    scope = False

    @abstractmethod
    def check(self, offer):
        """Return None if the offer passes, otherwise a reason string."""


class DestinationConstraint(Constraint):
    name = "destination"
    scope = True

    def __init__(self, destination_id):
        self.destination_id = destination_id

    def check(self, offer):
        if offer.destination.destination_id != self.destination_id:
            return f"goes to {offer.destination.destination_id}, not {self.destination_id}"
        return None


class DateWindowConstraint(Constraint):
    name = "travel window"
    scope = True

    def __init__(self, earliest, latest):
        self.earliest = earliest
        self.latest = latest

    def check(self, offer):
        if not self.earliest <= offer.travel_date <= self.latest:
            return f"departs {offer.travel_date}, outside {self.earliest} to {self.latest}"
        return None


class BudgetConstraint(Constraint):
    name = "budget"

    def __init__(self, max_price_eur):
        self.max_price_eur = max_price_eur

    def check(self, offer):
        if offer.price_eur > self.max_price_eur:
            return f"costs EUR {offer.price_eur:.2f}, above the budget of EUR {self.max_price_eur:.2f}"
        return None


def original_seats(offer):
    return offer.available_seats


class SeatsConstraint(Constraint):
    """Enough seats must be left for the whole party.

    seats_left is a function giving the seats still free on an offer. By
    default it uses the offer file. When bookings exist, the booking store's
    seats_left is passed in, so booked seats are taken into account.
    """

    name = "seats"

    def __init__(self, seats_needed, seats_left=original_seats):
        self.seats_needed = seats_needed
        self.seats_left = seats_left

    def check(self, offer):
        left = self.seats_left(offer)
        if left < self.seats_needed:
            return f"has {left} seat(s) left, {self.seats_needed} needed"
        return None


class TransfersConstraint(Constraint):
    name = "transfers"

    def __init__(self, max_transfers):
        self.max_transfers = max_transfers

    def check(self, offer):
        if offer.transfers > self.max_transfers:
            return f"has {offer.transfers} transfer(s), maximum is {self.max_transfers}"
        return None


class ChangeLevelConstraint(Constraint):
    """The ticket must allow at least a given level of change.

    Levels are ordered none < fee < free. "fee" means any changeable ticket
    is acceptable. "free" means changes must not cost extra.
    """

    name = "change level"

    def __init__(self, min_level):
        self.min_level = min_level

    def check(self, offer):
        if CHANGE_OPTIONS.index(offer.fare.changeable) < CHANGE_OPTIONS.index(self.min_level):
            return f"ticket allows '{offer.fare.changeable}' changes, '{self.min_level}' or better needed"
        return None


class MaxDurationConstraint(Constraint):
    name = "duration"

    def __init__(self, max_minutes):
        self.max_minutes = max_minutes

    def check(self, offer):
        if offer.duration_minutes > self.max_minutes:
            return f"takes {offer.duration_minutes} min, maximum is {self.max_minutes}"
        return None


def constraints_for(profile, seats_left=original_seats):
    """Build the list of hard constraints that apply to one traveller."""
    constraints = [
        DestinationConstraint(profile.destination_id),
        DateWindowConstraint(profile.earliest_date, profile.latest_date),
        BudgetConstraint(profile.max_price_eur),
        SeatsConstraint(profile.seats_needed, seats_left),
        TransfersConstraint(profile.max_transfers),
    ]
    if profile.min_change_level != "none":
        constraints.append(ChangeLevelConstraint(profile.min_change_level))
    if profile.max_duration_minutes is not None:
        constraints.append(MaxDurationConstraint(profile.max_duration_minutes))
    return constraints


@dataclass(frozen=True)
class Removal:
    """An offer that failed one or more hard constraints, with every reason."""

    offer: object
    failures: tuple  # (constraint name, reason) pairs


@dataclass
class FilterResult:
    out_of_scope: int = 0
    accepted: list = field(default_factory=list)
    removed: list = field(default_factory=list)

    @property
    def in_scope(self):
        return len(self.accepted) + len(self.removed)

    def counts_by_constraint(self):
        """How many in-scope offers failed each constraint.

        An offer can fail several constraints, so the counts can add up to
        more than the number of removed offers.
        """
        counts = Counter()
        for removal in self.removed:
            for name, _ in removal.failures:
                counts[name] += 1
        return counts

    def summary(self):
        text = f"{self.in_scope} offers match the route and dates. Removed {len(self.removed)}"
        counts = self.counts_by_constraint()
        if counts:
            details = ", ".join(f"{count} {name}" for name, count in counts.most_common())
            text += f" ({details})"
        return text + f". {len(self.accepted)} remain."


def filter_offers(offers, constraints):
    """Split offers into accepted and removed, recording every failed constraint."""
    result = FilterResult()
    scope_rules = [c for c in constraints if c.scope]
    hard_rules = [c for c in constraints if not c.scope]

    for offer in offers:
        if any(rule.check(offer) for rule in scope_rules):
            result.out_of_scope += 1
            continue
        failures = []
        for rule in hard_rules:
            reason = rule.check(offer)
            if reason:
                failures.append((rule.name, reason))
        if failures:
            result.removed.append(Removal(offer, tuple(failures)))
        else:
            result.accepted.append(offer)
    return result
