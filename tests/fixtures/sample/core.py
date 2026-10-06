"""Sample core module used by the Graphwright test-suite."""

from .util import Base, helper


class Engine(Base):
    """A tiny engine that exercises the graph builder."""

    def run(self, value):
        """Run the engine over a value."""
        return self.step(helper(value))

    def step(self, value):
        """Double a value."""
        return value * 2


def build_engine():
    """Create an engine and run it once."""
    engine = Engine()
    return engine.run(3)
