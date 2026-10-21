"""Simulated bookings: references, booking records and the booking file.

The source offers file is never changed. Bookings are stored separately in
a JSON file (state/bookings.json by default), and the seats left on an offer
are its original seats minus the seats already booked on it. Each booking
stores its own copy of the fare conditions, so it keeps the conditions that
were sold even if the offer data changes later. No payment details are
handled. Payment status is simulated.
"""

import json
import logging
import os
import random
import re
import tempfile
from datetime import datetime
from pathlib import Path

from .errors import BookingError, DataFileError, InvalidValueError
from .models import FareConditions
from .validation import Bounded, validate_identifier

logger = logging.getLogger(__name__)

DEFAULT_BOOKINGS_PATH = Path("state") / "bookings.json"

# Letters and digits that are easy to read aloud: no 0/O and no 1/I.
REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
BOOKING_REFERENCE_PATTERN = re.compile(r"BB-\d{4}-[A-HJ-NP-Z2-9]{6}")
SIMULATED_PAYMENT_STATUS = "paid (simulated)"


def generate_reference(rng, year, existing):
    """Return a new reference such as BB-2026-7K4QXM that is not in existing."""
    while True:
        code = "".join(rng.choice(REFERENCE_ALPHABET) for _ in range(6))
        reference = f"BB-{year}-{code}"
        if reference not in existing:
            return reference


class Booking:

    seats = Bounded(minimum=1, whole_number=True)
    price_per_seat_eur = Bounded(minimum=0)

    def __init__(self, reference, offer_id, company_id, destination_id, departure,
                 seats, price_per_seat_eur, fare, profile_name, booked_at,
                 payment_status=SIMULATED_PAYMENT_STATUS):
        self.reference = validate_identifier("reference", reference, BOOKING_REFERENCE_PATTERN)
        self.offer_id = offer_id
        self.company_id = company_id
        self.destination_id = destination_id
        self.departure = departure
        self.seats = seats
        self.price_per_seat_eur = price_per_seat_eur
        self.fare = fare.copy()
        self.profile_name = profile_name
        self.booked_at = booked_at
        self.payment_status = payment_status

    @property
    def total_price_eur(self):
        return round(self.seats * self.price_per_seat_eur, 2)

    def to_dict(self):
        return {
            "reference": self.reference,
            "offer_id": self.offer_id,
            "company_id": self.company_id,
            "destination_id": self.destination_id,
            "departure": self.departure.isoformat(timespec="minutes"),
            "seats": self.seats,
            "price_per_seat_eur": self.price_per_seat_eur,
            "total_price_eur": self.total_price_eur,
            "fare_type": self.fare.fare_type,
            "changeable": self.fare.changeable,
            "refundable": self.fare.refundable,
            "profile": self.profile_name,
            "booked_at": self.booked_at.isoformat(timespec="seconds"),
            "payment_status": self.payment_status,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a booking read from the file. Every value is checked again."""
        try:
            return cls(
                reference=data["reference"],
                offer_id=data["offer_id"],
                company_id=data["company_id"],
                destination_id=data["destination_id"],
                departure=datetime.fromisoformat(data["departure"]),
                seats=data["seats"],
                price_per_seat_eur=data["price_per_seat_eur"],
                fare=FareConditions(data["fare_type"], data["changeable"], data["refundable"]),
                profile_name=data["profile"],
                booked_at=datetime.fromisoformat(data["booked_at"]),
                payment_status=data["payment_status"],
            )
        except KeyError as error:
            raise InvalidValueError(str(error.args[0]), None, "is missing from the booking") from None
        except (TypeError, ValueError) as error:
            # InvalidValueError from the checks above is not a ValueError,
            # so it passes through unchanged with its own field and reason.
            raise InvalidValueError("booking", data, f"could not be read ({error})") from None

    def __repr__(self):
        return f"Booking({self.reference!r}, {self.offer_id!r}, seats={self.seats})"


class BookingStore:
    """All bookings, read from and written to one JSON file."""

    def __init__(self, path=DEFAULT_BOOKINGS_PATH, rng=None):
        self.path = Path(path)
        self.rng = rng or random.Random()
        self.bookings = self._load()

    def _load(self):
        if not self.path.exists():
            return []
        try:
            with open(self.path, encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as error:
            raise DataFileError(self.path, f"is not valid JSON (line {error.lineno}: {error.msg})") from None
        except OSError as error:
            raise DataFileError(self.path, f"could not be read ({error})") from None
        if not isinstance(data, list):
            raise DataFileError(self.path, "must contain a list of bookings")

        bookings = []
        seen = set()
        for position, item in enumerate(data, start=1):
            try:
                if not isinstance(item, dict):
                    raise InvalidValueError("booking", item, "must be an object")
                booking = Booking.from_dict(item)
                if booking.reference in seen:
                    raise InvalidValueError("reference", booking.reference, "appears more than once")
            except InvalidValueError as error:
                raise DataFileError(self.path, f"booking {position}: {error}") from None
            seen.add(booking.reference)
            bookings.append(booking)
        return bookings

    def save(self):
        """Write all bookings safely.

        The data is written to a temporary file in the same folder and then
        moved over the real file in one step, so a crash mid-write cannot
        leave a half-written bookings file.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [booking.to_dict() for booking in self.bookings]
        handle, temp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".bookings-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=2)
            os.replace(temp_name, self.path)
        except BaseException:
            if os.path.exists(temp_name):
                os.remove(temp_name)
            raise

    def references(self):
        return {booking.reference for booking in self.bookings}

    def find(self, reference):
        for booking in self.bookings:
            if booking.reference == reference:
                return booking
        return None

    def seats_booked(self, offer_id):
        return sum(booking.seats for booking in self.bookings if booking.offer_id == offer_id)

    def new_reference(self, year):
        return generate_reference(self.rng, year, self.references())

    def seats_left(self, offer):
        """Original seats on the offer minus seats already booked on it."""
        return offer.available_seats - self.seats_booked(offer.offer_id)

    def book(self, offer, seats, profile_name, booked_at=None):
        """Reserve seats on an offer, save the booking and return it.

        Seats are checked again at the moment of booking, because the
        ranking may be out of date. If saving fails, the booking is removed
        again so the store never holds a booking that is not on disk.
        """
        if isinstance(seats, bool) or not isinstance(seats, int) or seats < 1:
            raise BookingError(f"Number of seats must be a whole number of at least 1, not {seats!r}.")
        left = self.seats_left(offer)
        if seats > left:
            raise BookingError(
                f"{offer.offer_id} has {left} seat(s) left, so {seats} cannot be booked."
            )

        booking = Booking(
            reference=self.new_reference(offer.departure.year),
            offer_id=offer.offer_id,
            company_id=offer.company.company_id,
            destination_id=offer.destination.destination_id,
            departure=offer.departure,
            seats=seats,
            price_per_seat_eur=offer.price_eur,
            fare=offer.fare,
            profile_name=profile_name,
            booked_at=booked_at or datetime.now().replace(microsecond=0),
        )
        self.bookings.append(booking)
        try:
            self.save()
        except OSError as error:
            self.bookings.remove(booking)
            raise DataFileError(self.path, f"booking could not be saved ({error})") from None

        logger.info(
            "Booked %s: %d seat(s) on %s for profile %s, EUR %.2f, %d seat(s) left",
            booking.reference, seats, offer.offer_id, profile_name,
            booking.total_price_eur, self.seats_left(offer),
        )
        return booking
