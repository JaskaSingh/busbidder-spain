"""Validation rules shared across the application."""

import math

from .errors import InvalidValueError


class Bounded:
    """Descriptor for a numeric attribute with an optional minimum and maximum.

    Both boundaries are inclusive. The value is stored on the instance under
    a private name (price is stored as _price), and every assignment is
    checked, including the one made in __init__.
    """

    def __init__(self, minimum=None, maximum=None):
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("minimum cannot be greater than maximum")
        self.minimum = minimum
        self.maximum = maximum

    def __set_name__(self, owner, name):
        self.public_name = name
        self.private_name = "_" + name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return getattr(instance, self.private_name)

    def __set__(self, instance, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidValueError(self.public_name, value, "must be a number")
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
