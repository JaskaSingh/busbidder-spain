"""Validation rules shared across the application.

The functions in this module turn raw text from the data files into Python
values. Each one returns a clean value or raises InvalidValueError naming the
field, the value and the reason. Range rules for numbers live in the Bounded
descriptor, so the conversion functions only check that the text has the
right form.
"""

import math
import re
from datetime import datetime

from .errors import InvalidValueError

OFFER_ID_PATTERN = re.compile(r"OFR-\d{5}")
CODE_PATTERN = re.compile(r"[A-Z]{3}")

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"


def require_text(field, text):
    """Return the text without surrounding spaces, or raise if it is empty."""
    if text is None:
        raise InvalidValueError(field, text, "is missing")
    if not isinstance(text, str):
        # CSV fields are always text, but JSON values can be numbers or lists.
        raise InvalidValueError(field, text, "must be text")
    if text.strip() == "":
        raise InvalidValueError(field, text, "is missing")
    return text.strip()


def validate_identifier(field, text, pattern):
    """Return the text if the whole of it matches the pattern."""
    value = require_text(field, text)
    if not pattern.fullmatch(value):
        raise InvalidValueError(field, value, f"does not match {pattern.pattern}")
    return value


def clean_code(field, text):
    """Return a three-letter code in upper case.

    Spaces and lower case are corrected because they cannot change the
    meaning of a code. The caller compares the result with the original text
    to decide whether to log a correction.
    """
    value = require_text(field, text).upper()
    if not CODE_PATTERN.fullmatch(value):
        raise InvalidValueError(field, text, "must be three letters")
    return value


def to_int(field, text):
    value = require_text(field, text)
    try:
        return int(value)
    except ValueError:
        raise InvalidValueError(field, value, "is not a whole number") from None


def to_float(field, text):
    """Convert text to a float.

    Python accepts "nan" and "inf" here. They are rejected later by the
    Bounded descriptor, which owns all rules about allowed numbers.
    """
    value = require_text(field, text)
    try:
        return float(value)
    except ValueError:
        raise InvalidValueError(field, value, "is not a number") from None


def to_optional_float(field, text):
    """Like to_float, but an empty value means "not reported" and gives None."""
    if text is None or text.strip() == "":
        return None
    return to_float(field, text)


def parse_date(field, text):
    value = require_text(field, text)
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        raise InvalidValueError(field, value, "is not a valid date (YYYY-MM-DD)") from None


def parse_time(field, text):
    value = require_text(field, text)
    try:
        return datetime.strptime(value, TIME_FORMAT).time()
    except ValueError:
        raise InvalidValueError(field, value, "is not a valid time (HH:MM)") from None


def parse_choice(field, text, allowed):
    """Return the text if it is one of the allowed words."""
    value = require_text(field, text)
    if value not in allowed:
        options = ", ".join(sorted(allowed))
        raise InvalidValueError(field, value, f"must be one of: {options}")
    return value


def parse_yes_no(field, text):
    return parse_choice(field, text, {"yes", "no"}) == "yes"


class Bounded:
    """Descriptor for a numeric attribute with an optional minimum and maximum.

    Both boundaries are inclusive. The value is stored on the instance under
    a private name (price is stored as _price), and every assignment is
    checked, including the one made in __init__.

    whole_number=True rejects floats (for seats and transfers).
    optional=True allows None for values a company may not report.
    """

    def __init__(self, minimum=None, maximum=None, whole_number=False, optional=False):
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("minimum cannot be greater than maximum")
        self.minimum = minimum
        self.maximum = maximum
        self.whole_number = whole_number
        self.optional = optional

    def __set_name__(self, owner, name):
        self.public_name = name
        self.private_name = "_" + name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return getattr(instance, self.private_name)

    def __set__(self, instance, value):
        if value is None and self.optional:
            setattr(instance, self.private_name, None)
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidValueError(self.public_name, value, "must be a number")
        if self.whole_number and not isinstance(value, int):
            raise InvalidValueError(self.public_name, value, "must be a whole number")
        if not math.isfinite(value):
            raise InvalidValueError(self.public_name, value, "must be a finite number")
        if self.minimum is not None and value < self.minimum:
            raise InvalidValueError(
                self.public_name, value, f"must be at least {self.minimum}"
            )
        if self.maximum is not None and value > self.maximum:
            raise InvalidValueError(
                self.public_name, value, f"must be at most {self.maximum}"
            )
        setattr(instance, self.private_name, value)
