"""Sample helper module used by the Graphwright test-suite."""

import os


class Base:
    """Base class for the sample engine."""

    def greet(self, name):
        """Return a greeting for a name."""
        return "hello %s" % name


def helper(value):
    """Return the value unchanged."""
    return value


def platform_name():
    """Return the current platform name."""
    return os.name
