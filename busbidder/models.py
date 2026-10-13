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


class Offer:
    """One bookable departure from one company.

    An Offer is built from other objects (composition): it has a Company, a
    Destination and a FareConditions. Departure and arrival are full
    datetimes, so overnight journeys are handled correctly and duration is
    always calculated, never stored.
    """

    price_eur = Bounded(minimum=0)
    transfers = Bounded(minimum=0, whole_number=True)
    luggage_kg = Bounded(minimum=0)
    available_seats = Bounded(minimum=0, whole_number=True)
    rating = Bounded(minimum=1, maximum=5)
    co2_kg = Bounded(minimum=0, optional=True)

    def __init__(self, offer_id, company, destination, fare, departure, arrival,
                 price_eur, transfers, luggage_kg, available_seats, rating, co2_kg=None):
        if arrival <= departure:
            raise InvalidValueError(
                "arrival", arrival.strftime("%Y-%m-%d %H:%M"), "must be after departure"
            )
        self.offer_id = offer_id
        self.company = company
        self.destination = destination
        self.fare = fare
        self.departure = departure
        self.arrival = arrival
        self.price_eur = price_eur
        self.transfers = transfers
        self.luggage_kg = luggage_kg
        self.available_seats = available_seats
        self.rating = rating
        self.co2_kg = co2_kg

    @property
    def duration_minutes(self):
        return int((self.arrival - self.departure).total_seconds() // 60)

    @property
    def travel_date(self):
        """The date the journey starts, used for the traveller's date window."""
        return self.departure.date()

    def __repr__(self):
        return (
            f"Offer({self.offer_id!r}, {self.company.company_id}, "
            f"{self.destination.destination_id}, {self.departure:%Y-%m-%d %H:%M}, "
            f"EUR {self.price_eur:.2f})"
        )
