"""Normalisation + derived price helpers over the API response."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime

    from .models import HourlyTariffDetails, Tariff

# Which component to use as the headline price.
PRICE_GROSS = "gross"  # all-in incl. VAT (default; what you pay)
PRICE_NET = "net"  # all-in excl. VAT


def _price(t: Tariff, price_type: str) -> float:
    return t.total.net if price_type == PRICE_NET else t.total.gross


@dataclass(slots=True)
class PriceSlot:
    """One hourly price slot."""

    start: datetime
    end: datetime
    price: float

    def as_attr(self) -> dict:
        """Serialize to a JSON-friendly dict (ISO timestamps, rounded price)."""
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "price": round(self.price, 6),
        }


class PriceData:
    """Wraps a fetched response and exposes derived values for consumers."""

    def __init__(self, details: HourlyTariffDetails, price_type: str) -> None:
        """Flatten the response into de-duplicated, sorted price slots."""
        self.price_type = price_type
        by_start: dict[datetime, Tariff] = {}
        for day in details.days:
            for t in day.electricity:
                by_start[t.period_from] = t
        self._tariffs: list[Tariff] = [by_start[k] for k in sorted(by_start)]
        self.slots: list[PriceSlot] = [
            PriceSlot(t.period_from, t.period_to, _price(t, price_type))
            for t in self._tariffs
        ]

    # -- current / next -----------------------------------------------------
    def current_tariff(self, now: datetime) -> Tariff | None:
        """The full tariff (with cost components) covering `now`."""
        for t in self._tariffs:
            if t.period_from <= now < t.period_to:
                return t
        return None

    def current_slot(self, now: datetime) -> PriceSlot | None:
        """The price slot covering `now`."""
        for s in self.slots:
            if s.start <= now < s.end:
                return s
        return None

    def next_slot(self, now: datetime) -> PriceSlot | None:
        """The first slot starting after `now`."""
        upcoming = [s for s in self.slots if s.start > now]
        return min(upcoming, key=lambda s: s.start) if upcoming else None

    # -- today aggregates ---------------------------------------------------
    def _today(self, ref: date) -> list[PriceSlot]:
        return [s for s in self.slots if s.start.date() == ref]

    def average_today(self, now: datetime) -> float | None:
        """Mean price over today's slots."""
        today = self._today(now.date())
        return sum(s.price for s in today) / len(today) if today else None

    def lowest_today(self, now: datetime) -> PriceSlot | None:
        """Today's cheapest slot."""
        today = self._today(now.date())
        return min(today, key=lambda s: s.price) if today else None

    def highest_today(self, now: datetime) -> PriceSlot | None:
        """Today's most expensive slot."""
        today = self._today(now.date())
        return max(today, key=lambda s: s.price) if today else None

    def percentage_of_max(self, now: datetime) -> float | None:
        """Current price as a percentage of today's maximum."""
        cur = self.current_slot(now)
        hi = self.highest_today(now)
        if cur is None or hi is None or hi.price == 0:
            return None
        return round(cur.price / hi.price * 100, 1)

    # -- forecast attributes ------------------------------------------------
    def prices_for(self, ref: date) -> list[dict]:
        """All slots for the given date, serialized via `as_attr`."""
        return [s.as_attr() for s in self._today(ref)]

    def tomorrow_valid(self, now: datetime) -> bool:
        """Whether tomorrow's prices have been published yet."""
        tomorrow = now.date().toordinal() + 1
        return any(s.start.date().toordinal() == tomorrow for s in self.slots)
