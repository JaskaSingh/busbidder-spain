"""A small reusable registry of named functions.

Used for scoring criteria, normalisation strategies and experiments. Each registry
gives a decorator that stores a function under a name, a lookup that gives a
clear error for unknown names, and a sorted list of what is available.
"""

from .errors import RegistryError


class Registry:

    def __init__(self, kind):
        self.kind = kind  # used in error messages, for example "criterion"
        self._items = {}

    def register(self, name):
        """Decorator factory: @registry.register("name") stores the function."""

        def decorator(function):
            if name in self._items:
                raise RegistryError(name, f"is already registered as a {self.kind}")
            self._items[name] = function
            return function

        return decorator

    def get(self, name):
        try:
            return self._items[name]
        except KeyError:
            available = ", ".join(self.names())
            raise RegistryError(name, f"is not a known {self.kind} (available: {available})") from None

    def names(self):
        return sorted(self._items)

    def remove(self, name):
        """Remove a name. Only used by tests that register temporary items."""
        self._items.pop(name, None)

    def __contains__(self, name):
        return name in self._items
