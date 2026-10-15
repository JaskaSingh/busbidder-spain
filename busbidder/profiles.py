"""Traveller profiles: hard constraints and preference weights.

A profile is one traveller's request. Its hard constraints (destination,
dates, budget, seats, transfers, changeability, maximum duration) decide
which offers are acceptable at all. Its weights decide how acceptable offers
are ranked. Keeping both in the profile means the same attribute can be a
hard rule for one traveller and only a preference for another.
"""

import json

from .errors import ConfigError, DataFileError, InvalidValueError
from .validation import Bounded, clean_code, parse_date, parse_time, require_text

PROFILE_KEYS = {
    "label", "destination_id", "earliest_date", "latest_date", "max_price_eur",
    "seats_needed", "max_transfers", "changeable_required", "max_duration_minutes",
    "preferred_departure_from", "preferred_departure_to", "weights",
}
WEIGHT_TOTAL = 100


def validate_weights(weights):
    """Return the weights if they are whole, non-negative percentages totalling 100.

    Whole percentages avoid float sums such as 0.4 + 0.25 + 0.15 + 0.2 not
    being exactly 1.0. Wrong totals are rejected rather than rescaled, so the
    traveller always sees the weights that are actually used.
    """
    if not isinstance(weights, dict) or not weights:
        raise InvalidValueError("weights", weights, "must be a non-empty mapping of criterion to percentage")
    for name, weight in weights.items():
        if isinstance(weight, bool) or not isinstance(weight, int):
            raise InvalidValueError(f"weights.{name}", weight, "must be a whole percentage")
        if weight < 0:
            raise InvalidValueError(f"weights.{name}", weight, "must not be negative")
    total = sum(weights.values())
    if total != WEIGHT_TOTAL:
        raise InvalidValueError("weights", total, f"must add up to {WEIGHT_TOTAL}")
    return dict(weights)


class TravellerProfile:

    max_price_eur = Bounded(minimum=0)
    seats_needed = Bounded(minimum=1, whole_number=True)
    max_transfers = Bounded(minimum=0, whole_number=True)
    max_duration_minutes = Bounded(minimum=1, whole_number=True, optional=True)

    def __init__(self, name, label, destination_id, earliest_date, latest_date,
                 max_price_eur, seats_needed, max_transfers, changeable_required,
                 max_duration_minutes, preferred_departure_from,
                 preferred_departure_to, weights):
        if latest_date < earliest_date:
            raise InvalidValueError("latest_date", str(latest_date), "is before earliest_date")
        if not isinstance(changeable_required, bool):
            raise InvalidValueError("changeable_required", changeable_required, "must be true or false")
        if preferred_departure_from == preferred_departure_to:
            raise InvalidValueError(
                "preferred_departure_to", str(preferred_departure_to),
                "must differ from preferred_departure_from",
            )
        self.name = name
        self.label = label
        self.destination_id = destination_id
        self.earliest_date = earliest_date
        self.latest_date = latest_date
        self.max_price_eur = max_price_eur
        self.seats_needed = seats_needed
        self.max_transfers = max_transfers
        self.changeable_required = changeable_required
        self.max_duration_minutes = max_duration_minutes
        self.preferred_departure_from = preferred_departure_from
        self.preferred_departure_to = preferred_departure_to
        self.weights = validate_weights(weights)

    def __repr__(self):
        return f"TravellerProfile({self.name!r}, {self.label!r})"


def _profile_from_dict(name, data):
    unknown = set(data) - PROFILE_KEYS
    if unknown:
        raise InvalidValueError("profile", ", ".join(sorted(unknown)), "has unknown key(s)")
    missing = PROFILE_KEYS - set(data)
    if missing:
        raise InvalidValueError("profile", ", ".join(sorted(missing)), "is missing key(s)")

    return TravellerProfile(
        name=name,
        label=require_text("label", data["label"]),
        destination_id=clean_code("destination_id", data["destination_id"]),
        earliest_date=parse_date("earliest_date", data["earliest_date"]),
        latest_date=parse_date("latest_date", data["latest_date"]),
        max_price_eur=data["max_price_eur"],
        seats_needed=data["seats_needed"],
        max_transfers=data["max_transfers"],
        changeable_required=data["changeable_required"],
        max_duration_minutes=data["max_duration_minutes"],
        preferred_departure_from=parse_time("preferred_departure_from", data["preferred_departure_from"]),
        preferred_departure_to=parse_time("preferred_departure_to", data["preferred_departure_to"]),
        weights=data["weights"],
    )


def load_profiles(path):
    """Load all profiles from a JSON file into a dictionary keyed by name."""
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        raise DataFileError(path, "file not found") from None
    except json.JSONDecodeError as error:
        raise ConfigError(path, f"is not valid JSON (line {error.lineno}: {error.msg})") from None

    if not isinstance(data, dict) or not data:
        raise ConfigError(path, "must contain at least one named profile")

    profiles = {}
    for name, profile_data in data.items():
        if not isinstance(profile_data, dict):
            raise ConfigError(path, f"profile '{name}' must be an object")
        try:
            profiles[name] = _profile_from_dict(name, profile_data)
        except InvalidValueError as error:
            raise ConfigError(path, f"profile '{name}': {error}") from None
    return profiles
