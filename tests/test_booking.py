import json
import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from busbidder.booking import (
    BOOKING_REFERENCE_PATTERN,
    Booking,
    BookingStore,
    generate_reference,
)
from busbidder.errors import BookingError, DataFileError, InvalidValueError
from busbidder.filtering import constraints_for, filter_offers
from busbidder.models import FareConditions
from tests.test_filtering import make_profile
from tests.test_models import make_offer

BOOKED_AT = datetime(2026, 10, 20, 12, 0, 0)


def make_booking(reference="BB-2026-7K4QXM", offer_id="OFR-00186", seats=1, **changes):
    values = dict(
        reference=reference,
        offer_id=offer_id,
        company_id="CAM",
        destination_id="MAL",
        departure=datetime(2026, 7, 12, 11, 30),
        seats=seats,
        price_per_seat_eur=76.70,
        fare=FareConditions("flex", "free", True),
        profile_name="business",
        booked_at=BOOKED_AT,
    )
    values.update(changes)
    return Booking(**values)


class ReferenceTests(unittest.TestCase):

    def test_generated_reference_matches_pattern(self):
        reference = generate_reference(random.Random(1), 2026, set())
        self.assertRegex(reference, r"^BB-2026-")
        self.assertTrue(BOOKING_REFERENCE_PATTERN.fullmatch(reference))

    def test_existing_reference_is_never_reused(self):
        first = generate_reference(random.Random(7), 2026, set())
        second = generate_reference(random.Random(7), 2026, {first})
        self.assertNotEqual(first, second)

    def test_malformed_references_are_rejected(self):
        for bad in ("BB-2026-7K4QX", "BB-2026-7K4QXO", "bb-2026-7K4QXM", "BB-26-7K4QXM", "XBB-2026-7K4QXM"):
            with self.subTest(reference=bad):
                with self.assertRaises(InvalidValueError):
                    make_booking(reference=bad)


class BookingTests(unittest.TestCase):

    def test_total_price(self):
        self.assertEqual(make_booking(seats=2).total_price_eur, 153.40)

    def test_zero_seats_is_rejected(self):
        with self.assertRaises(InvalidValueError):
            make_booking(seats=0)

    def test_fare_conditions_are_copied(self):
        fare = FareConditions("flex", "free", True)
        booking = make_booking(fare=fare)
        self.assertEqual(booking.fare, fare)
        self.assertIsNot(booking.fare, fare)

    def test_round_trip_through_dict(self):
        original = make_booking(seats=2)
        copy = Booking.from_dict(original.to_dict())
        self.assertEqual(copy.to_dict(), original.to_dict())


class BookingStoreTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state" / "bookings.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_file_means_no_bookings(self):
        self.assertEqual(BookingStore(self.path).bookings, [])

    def test_save_and_load_again(self):
        store = BookingStore(self.path)
        store.bookings.append(make_booking())
        store.bookings.append(make_booking("BB-2026-ABCDEF", "OFR-00398", seats=2))
        store.save()

        reloaded = BookingStore(self.path)
        self.assertEqual([b.reference for b in reloaded.bookings], ["BB-2026-7K4QXM", "BB-2026-ABCDEF"])
        self.assertEqual(reloaded.seats_booked("OFR-00398"), 2)
        self.assertEqual(reloaded.find("BB-2026-7K4QXM").fare.describe(), "free change, refundable")

    def test_save_leaves_no_temporary_files(self):
        store = BookingStore(self.path)
        store.bookings.append(make_booking())
        store.save()
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["bookings.json"])

    def test_corrupt_file_is_reported(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("[ not json", encoding="utf-8")
        with self.assertRaises(DataFileError):
            BookingStore(self.path)

    def test_bad_reference_in_file_is_reported_with_position(self):
        self.path.parent.mkdir(parents=True)
        data = make_booking().to_dict()
        data["reference"] = "BB-2026-BAD"
        self.path.write_text(json.dumps([data]), encoding="utf-8")
        with self.assertRaises(DataFileError) as context:
            BookingStore(self.path)
        self.assertIn("booking 1", context.exception.reason)

    def test_duplicate_reference_in_file_is_reported(self):
        self.path.parent.mkdir(parents=True)
        data = make_booking().to_dict()
        self.path.write_text(json.dumps([data, data]), encoding="utf-8")
        with self.assertRaises(DataFileError):
            BookingStore(self.path)

    def test_missing_field_in_file_is_reported(self):
        self.path.parent.mkdir(parents=True)
        data = make_booking().to_dict()
        del data["seats"]
        self.path.write_text(json.dumps([data]), encoding="utf-8")
        with self.assertRaises(DataFileError) as context:
            BookingStore(self.path)
        self.assertIn("seats", context.exception.reason)


class SeatReservationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "bookings.json"
        self.store = BookingStore(self.path, rng=random.Random(42))
        self.offer = make_offer(
            offer_id="OFR-00001",
            available_seats=3,
            departure=datetime(2026, 7, 13, 10, 0),
            arrival=datetime(2026, 7, 13, 17, 0),
        )

    def tearDown(self):
        self.temp.cleanup()

    def book(self, seats=1):
        return self.store.book(self.offer, seats, "budget", booked_at=BOOKED_AT)

    def test_booking_reduces_seats_left_and_keeps_offer_unchanged(self):
        booking = self.book(2)
        self.assertEqual(self.store.seats_left(self.offer), 1)
        self.assertEqual(self.offer.available_seats, 3)
        self.assertEqual(booking.total_price_eur, round(2 * self.offer.price_eur, 2))
        self.assertEqual(booking.fare, self.offer.fare)

    def test_last_seat_can_be_booked_then_next_attempt_fails(self):
        self.book(2)
        self.book(1)
        self.assertEqual(self.store.seats_left(self.offer), 0)
        with self.assertRaises(BookingError):
            self.book(1)

    def test_too_many_seats_fails_and_nothing_is_saved(self):
        with self.assertRaises(BookingError):
            self.book(4)
        self.assertEqual(self.store.bookings, [])
        self.assertFalse(self.path.exists())

    def test_invalid_seat_counts_are_refused(self):
        for bad in (0, -1, 1.5, True, "2"):
            with self.subTest(seats=bad):
                with self.assertRaises(BookingError):
                    self.book(bad)

    def test_bookings_survive_a_restart(self):
        first = self.book(2)
        restarted = BookingStore(self.path)
        self.assertEqual(restarted.seats_left(self.offer), 1)
        self.assertEqual(restarted.find(first.reference).seats, 2)

    def test_every_booking_gets_a_unique_reference(self):
        references = {self.book(1).reference for _ in range(3)}
        self.assertEqual(len(references), 3)

    def test_failed_save_leaves_no_booking_behind(self):
        def broken_save():
            raise OSError("disk full")
        self.store.save = broken_save
        with self.assertRaises(DataFileError):
            self.book(1)
        self.assertEqual(self.store.bookings, [])
        self.assertEqual(self.store.seats_left(self.offer), 3)

    def test_filtering_uses_seats_left_after_bookings(self):
        profile = make_profile(seats_needed=2)
        self.book(2)
        before = filter_offers([self.offer], constraints_for(profile))
        after = filter_offers([self.offer], constraints_for(profile, self.store.seats_left))
        self.assertEqual(before.accepted, [self.offer])
        self.assertEqual(after.accepted, [])
        self.assertEqual(after.counts_by_constraint(), {"seats": 1})


if __name__ == "__main__":
    unittest.main()
