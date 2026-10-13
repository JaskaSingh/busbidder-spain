"""Domain objects for BusBidder Spain.

Each class checks its own values in __init__, so an object can never exist
in an invalid state. Numeric ranges use the Bounded descriptor. The loader
builds these objects from text and records any InvalidValueError as a
rejected row.
"""

from .errors import InvalidValueError
from .validation import Bounded

CHANGE_OPTIONS = ("none", "fee", "free")


class Company:
    """A bus company. Holds identity only, not behaviour (see the generator)."""

    def __init__(self, company_id, name, profile):
        self.company_id = company_id
        self.name = name
        self.profile = profile

    def __repr__(self):
        return f"Company({self.company_id!r}, {self.name!r})"


class Destination:
    """A destination served from Madrid."""

    distance_km = Bounded(minimum=1)

    def __init__(self, destination_id, name, distance_km, coastal):
        self.destination_id = destination_id
        self.name = name
        self.distance_km = distance_km
        self.coastal = coastal

    def __repr__(self):
        return f"Destination({self.destination_id!r}, {self.name!r}, {self.distance_km} km)"


class FareConditions:
    """The ticket rules that come with an offer.

    A booking stores its own copy of these, so later changes to an offer
    cannot change the conditions a traveller already bought.
    """

    def __init__(self, fare_type, changeable, refundable):
        if changeable not in CHANGE_OPTIONS:
            raise InvalidValueError(
                "changeable", changeable, f"must be one of: {', '.join(CHANGE_OPTIONS)}"
            )
        if not isinstance(refundable, bool):
            raise InvalidValueError("refundable", refundable, "must be True or False")
        self.fare_type = fare_type
        self.changeable = changeable
        self.refundable = refundable

    def describe(self):
        """Short text for tables and explanations, for example 'free change, refundable'."""
        change_text = {
            "none": "no changes",
            "fee": "change for a fee",
            "free": "free change",
        }[self.changeable]
        refund_text = "refundable" if self.refundable else "non-refundable"
        return f"{change_text}, {refund_text}"

    def copy(self):
        return FareConditions(self.fare_type, self.changeable, self.refundable)

    def __eq__(self, other):
        if not isinstance(other, FareConditions):
            return NotImplemented
        return (self.fare_type, self.changeable, self.refundable) == (
            other.fare_type, other.changeable, other.refundable
        )

    def __repr__(self):
        return f"FareConditions({self.fare_type!r}, {self.changeable!r}, {self.refundable})"
