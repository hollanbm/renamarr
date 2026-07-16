from typing import NamedTuple


class Interval(NamedTuple):
    """A recurring Renamarr interval."""

    days: int
    hours: int
    minutes: int

    @property
    def total_minutes(self) -> int:
        """Return the complete interval in minutes."""
        return self.days * 1440 + self.hours * 60 + self.minutes
