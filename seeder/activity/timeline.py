"""When the seeded activity happened: fourteen days ending now, mostly in working hours."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from random import Random

DAYS = 14
ENFORCED_DAYS = 7
LATE_ENFORCED_DAYS = 3
# Office hours in UTC, which is roughly 08:00 to 19:00 in Athens.
OPENS = time(6, 0)
CLOSES = time(17, 0)
WEEKEND_WEIGHT = 0.12


@dataclass(frozen=True)
class Timeline:
    """The seeded fortnight. The first week is observed only; then the gateway enforces."""

    now: datetime

    @property
    def start(self) -> datetime:
        midnight = datetime.combine(self.now.date(), time(0), tzinfo=UTC)
        return midnight - timedelta(days=DAYS - 1)

    @property
    def enforced_from(self) -> datetime:
        return self.now - timedelta(days=ENFORCED_DAYS)

    @property
    def late_enforced_from(self) -> datetime:
        """One team joined the gateway late, so its prompts stayed unmasked for longer."""
        return self.now - timedelta(days=LATE_ENFORCED_DAYS)

    def working_windows(
        self, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime, float]]:
        """Office-hours windows between `start` and `end`, each with its share of activity."""
        windows = []
        day = start.date()
        while day <= end.date():
            opens = max(datetime.combine(day, OPENS, tzinfo=UTC), start)
            closes = min(datetime.combine(day, CLOSES, tzinfo=UTC), end)
            if closes > opens:
                hours = (closes - opens).total_seconds() / 3600
                weight = hours * (WEEKEND_WEIGHT if day.weekday() >= 5 else 1.0)
                windows.append((opens, closes, weight))
            day += timedelta(days=1)
        return windows

    def sample(self, rng: Random, count: int, start: datetime, end: datetime) -> list[datetime]:
        """`count` moments between `start` and `end`, in office hours when there are any."""
        windows = self.working_windows(start, end) or [(start, end, 1.0)]
        weights = [weight for _, _, weight in windows]
        moments = []
        for opens, closes, _ in rng.choices(windows, weights=weights, k=count):
            seconds = (closes - opens).total_seconds()
            moments.append(opens + timedelta(seconds=rng.uniform(0, seconds)))
        return sorted(moments)
