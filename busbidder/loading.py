"""Reading the data files into model objects.

Reference files (companies and destinations) must be completely valid. A bad
row there stops loading with a DataFileError, because every offer depends on
them.

Offer files are handled row by row. Each row ends up in exactly one of three
places in the LoadResult:
- offers: valid and plausible, used for ranking
- rejected: impossible values, with the field and reason
- review: possible but suspicious, kept out of ranking until a person checks
Safe corrections (spaces and case in codes) are recorded in corrections.
"""

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime

from .errors import DataFileError, InvalidValueError
from .models import Company, Destination, FareConditions, Offer
from .validation import (
    OFFER_ID_PATTERN,
    clean_code,
    parse_date,
    parse_time,
    parse_yes_no,
    require_text,
    to_float,
    to_int,
    to_optional_float,
    validate_identifier,
)

logger = logging.getLogger(__name__)

COMPANY_COLUMNS = ["company_id", "name", "profile"]
DESTINATION_COLUMNS = ["destination_id", "name", "distance_km", "coastal"]
OFFER_COLUMNS = [
    "offer_id", "company_id", "fare_type", "destination_id",
    "departure_date", "departure_time", "arrival_date", "arrival_time",
    "price_eur", "transfers", "luggage_kg", "changeable", "refundable",
    "available_seats", "rating", "co2_kg",
]

# Plausibility limits. Offers outside them are possible but suspicious, so
# they go to review instead of being rejected or ranked.
MIN_PLAUSIBLE_PRICE_EUR = 3.00
MAX_PLAUSIBLE_SPEED_KMH = 120


@dataclass(frozen=True)
class Issue:
    """One problem with one row, kept as structured data."""

    source: str
    line: int
    offer_id: str
    field: str
    value: object
    reason: str

    def describe(self):
        value = "" if self.value is None else f" = {self.value!r}"
        return f"{self.source} line {self.line} ({self.offer_id}): {self.field}{value} {self.reason}"


@dataclass(frozen=True)
class Correction:
    source: str
    line: int
    offer_id: str
    field: str
    original: str
    corrected: str


@dataclass
class LoadResult:
    offers: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    review: list = field(default_factory=list)
    corrections: list = field(default_factory=list)

    def summary(self):
        return (
            f"{len(self.offers)} accepted, {len(self.rejected)} rejected, "
            f"{len(self.review)} set aside for review, {len(self.corrections)} corrections"
        )


def read_rows(path, required_columns):
    """Return (line_number, row) pairs from a CSV file.

    Raises DataFileError if the file is missing, unreadable, empty or lacks a
    required column. Line numbers match what an editor shows, so the header
    is line 1 and the first data row is line 2.
    """
    try:
        with open(path, newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None:
                raise DataFileError(path, "file is empty")
            missing = [column for column in required_columns if column not in reader.fieldnames]
            if missing:
                raise DataFileError(path, f"missing column(s): {', '.join(missing)}")
            return [(reader.line_num, row) for row in reader]
    except FileNotFoundError:
        raise DataFileError(path, "file not found") from None
    except (OSError, UnicodeDecodeError) as error:
        raise DataFileError(path, f"could not be read ({error})") from None
    except csv.Error as error:
        raise DataFileError(path, f"is not valid CSV ({error})") from None


def _load_reference(path, columns, id_field, build):
    """Load a reference file into a dictionary keyed by ID.

    Any invalid or duplicate row raises DataFileError naming the line.
    """
    items = {}
    for line, row in read_rows(path, columns):
        try:
            item_id = clean_code(id_field, row[id_field])
            if item_id in items:
                raise InvalidValueError(id_field, item_id, "appears more than once")
            items[item_id] = build(item_id, row)
        except InvalidValueError as error:
            raise DataFileError(path, f"line {line}: {error}") from None
    logger.info("Loaded %d records from %s", len(items), path)
    return items


def load_companies(path):
    def build(company_id, row):
        return Company(
            company_id,
            require_text("name", row["name"]),
            require_text("profile", row["profile"]),
        )

    return _load_reference(path, COMPANY_COLUMNS, "company_id", build)


def load_destinations(path):
    def build(destination_id, row):
        return Destination(
            destination_id,
            require_text("name", row["name"]),
            to_int("distance_km", row["distance_km"]),
            parse_yes_no("coastal", row["coastal"]),
        )

    return _load_reference(path, DESTINATION_COLUMNS, "destination_id", build)


def load_offers(path, companies, destinations):
    """Load an offer file row by row into a LoadResult."""
    result = LoadResult()
    seen_ids = set()
    source = str(path)

    for line, row in read_rows(path, OFFER_COLUMNS):
        raw_id = (row.get("offer_id") or "").strip()
        try:
            offer = _build_offer(row, companies, destinations, seen_ids)
        except InvalidValueError as error:
            result.rejected.append(
                Issue(source, line, raw_id, error.field, error.value, error.reason)
            )
            continue

        cleaned_codes = (
            ("company_id", offer.company.company_id),
            ("destination_id", offer.destination.destination_id),
        )
        for field_name, corrected in cleaned_codes:
            original = row[field_name]
            if original != corrected:
                result.corrections.append(
                    Correction(source, line, offer.offer_id, field_name, original, corrected)
                )

        concern = plausibility_concern(offer)
        if concern:
            field_name, value, reason = concern
            result.review.append(Issue(source, line, offer.offer_id, field_name, value, reason))
        else:
            result.offers.append(offer)

    for issue in result.rejected:
        logger.warning("Rejected %s", issue.describe())
    for issue in result.review:
        logger.warning("Set aside for review %s", issue.describe())
    for correction in result.corrections:
        logger.info(
            "Corrected %s line %d (%s): %s %r to %r", correction.source, correction.line,
            correction.offer_id, correction.field, correction.original, correction.corrected,
        )
    logger.info("Loaded %s: %s", source, result.summary())
    return result


def _build_offer(row, companies, destinations, seen_ids):
    """Turn one CSV row into an Offer or raise InvalidValueError."""
    # csv.DictReader fills missing fields with None and puts extra fields
    # under the key None, so both mean the row has the wrong length.
    if None in row or any(value is None for value in row.values()):
        raise InvalidValueError("row", None, "has the wrong number of fields")

    offer_id = validate_identifier("offer_id", row["offer_id"], OFFER_ID_PATTERN)
    if offer_id in seen_ids:
        raise InvalidValueError("offer_id", offer_id, "appears more than once")
    seen_ids.add(offer_id)

    company_id = clean_code("company_id", row["company_id"])
    if company_id not in companies:
        raise InvalidValueError("company_id", company_id, "is not a known company")
    destination_id = clean_code("destination_id", row["destination_id"])
    if destination_id not in destinations:
        raise InvalidValueError("destination_id", destination_id, "is not a known destination")

    departure = datetime.combine(
        parse_date("departure_date", row["departure_date"]),
        parse_time("departure_time", row["departure_time"]),
    )
    arrival = datetime.combine(
        parse_date("arrival_date", row["arrival_date"]),
        parse_time("arrival_time", row["arrival_time"]),
    )

    fare = FareConditions(
        require_text("fare_type", row["fare_type"]),
        require_text("changeable", row["changeable"]),
        parse_yes_no("refundable", row["refundable"]),
    )

    return Offer(
        offer_id=offer_id,
        company=companies[company_id],
        destination=destinations[destination_id],
        fare=fare,
        departure=departure,
        arrival=arrival,
        price_eur=to_float("price_eur", row["price_eur"]),
        transfers=to_int("transfers", row["transfers"]),
        luggage_kg=to_float("luggage_kg", row["luggage_kg"]),
        available_seats=to_int("available_seats", row["available_seats"]),
        rating=to_float("rating", row["rating"]),
        co2_kg=to_optional_float("co2_kg", row["co2_kg"]),
    )


def plausibility_concern(offer):
    """Return (field, value, reason) if the offer looks suspicious, else None."""
    if offer.price_eur < MIN_PLAUSIBLE_PRICE_EUR:
        return ("price_eur", offer.price_eur,
                f"is below the plausible minimum of {MIN_PLAUSIBLE_PRICE_EUR:.2f}")
    speed = offer.destination.distance_km / (offer.duration_minutes / 60)
    if speed > MAX_PLAUSIBLE_SPEED_KMH:
        return ("duration", offer.duration_minutes,
                f"means an average speed of {speed:.0f} km/h, above {MAX_PLAUSIBLE_SPEED_KMH}")
    return None
