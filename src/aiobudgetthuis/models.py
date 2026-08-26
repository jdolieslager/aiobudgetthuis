"""Data models for the Budget Thuis API responses (stdlib only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

_AMS = ZoneInfo("Europe/Amsterdam")


def _dt(value: str) -> datetime:
    # API sends ISO-8601, usually with an offset (2026-08-24T00:00:00+02:00) but
    # occasionally naive. Always return tz-aware so timestamp consumers and
    # tz-aware "now" comparisons never raise.
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=_AMS) if dt.tzinfo is None else dt


def _dt_aware(value: str | None) -> datetime | None:
    """Parse a datetime, attaching Amsterdam tz when the API omits an offset."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.replace(tzinfo=_AMS) if dt.tzinfo is None else dt


def _nested(d: dict, *keys: str) -> object:
    cur: object = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _num(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class Amount:
    """A money amount split into net / VAT / gross components."""

    net: float
    vat: float
    gross: float

    @classmethod
    def from_dict(cls, d: dict | None) -> Amount | None:
        """Parse an amount payload; None when absent."""
        if not d:
            return None
        return cls(
            net=float(d.get("amountNet", 0.0)),
            vat=float(d.get("amountVat", 0.0)),
            gross=float(d.get("amountGross", 0.0)),
        )


@dataclass(slots=True)
class Tariff:
    """One hourly electricity tariff with its cost components."""

    total: Amount
    commodity: Amount | None
    energy_tax: Amount | None
    surcharge: Amount | None
    period_from: datetime
    period_to: datetime

    @classmethod
    def from_dict(cls, d: dict) -> Tariff:
        """Parse a tariff payload; requires totalTariff and the period bounds."""
        total = Amount.from_dict(d["totalTariff"])
        if total is None:
            raise KeyError("totalTariff")
        return cls(
            total=total,
            commodity=Amount.from_dict(d.get("commodity")),
            energy_tax=Amount.from_dict(d.get("energyTax")),
            surcharge=Amount.from_dict(d.get("surcharge")),
            period_from=_dt(d["periodFrom"]),
            period_to=_dt(d["periodTo"]),
        )


@dataclass(slots=True)
class TariffDay:
    """All electricity tariffs published for one calendar day."""

    date: datetime
    reason_no_tariffs: str | None
    electricity: list[Tariff] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> TariffDay:
        """Parse one tariffDays entry."""
        return cls(
            date=_dt(d["tariffsOfDate"]),
            reason_no_tariffs=d.get("reasonNoTariffs"),
            electricity=[Tariff.from_dict(t) for t in d.get("electricityTariffs", [])],
        )


@dataclass(slots=True)
class HourlyTariffDetails:
    """Response of the hourlytariff/details endpoint."""

    days: list[TariffDay] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> HourlyTariffDetails:
        """Parse the full hourlytariff/details response."""
        return cls(days=[TariffDay.from_dict(x) for x in d.get("tariffDays", [])])


@dataclass(slots=True)
class Contract:
    """A discovered contract (from productPicker)."""

    id: str
    status: str
    type: str
    label: str

    @property
    def is_active(self) -> bool:
        """Whether the contract status is Active (case-insensitive)."""
        return self.status.casefold() == "active"

    @classmethod
    def from_dict(cls, d: dict) -> Contract:
        """Parse a contractsInfo entry, deriving a human-readable label."""
        cid = str(d.get("contractId"))
        ctype = d.get("contractType") or ""
        addr = d.get("supplyAddress") or {}
        house = addr.get("houseNumber")
        street = " ".join(
            p
            for p in (addr.get("street"), str(house) if house is not None else None)
            if p
        ).strip()
        location = ", ".join(p for p in (street, addr.get("city")) if p)
        label = " - ".join(p for p in (location, ctype) if p) or f"Contract {cid}"
        return cls(
            id=cid, status=d.get("contractStatus") or "", type=ctype, label=label
        )


def relation_ids_from_contact_person(payload: dict) -> list[int]:
    """Extract productCustomerId values (relation ids) from /home/v1/contactPerson."""
    cp = payload.get("contactPerson") or {}
    ids: list[int] = []
    for customer in cp.get("customers") or []:
        for pc in customer.get("productCustomers") or []:
            pid = pc.get("productCustomerId")
            if pid is not None:
                ids.append(pid)
    return ids


@dataclass(slots=True)
class MonthlyAmount:
    """Monthly installment (advance amount) with the allowed adjustment range."""

    current_gross: float | None
    minimum: float | None
    maximum: float | None

    @classmethod
    def from_dict(cls, d: dict) -> MonthlyAmount:
        """Parse the monthlyAmount response."""
        return cls(
            current_gross=_num(_nested(d, "currentAdvanceAmount", "amountGross")),
            minimum=_num(d.get("minimumAdvanceAmount")),
            maximum=_num(d.get("maximumAdvanceAmount")),
        )


@dataclass(slots=True)
class UsageDay:
    """One day of electricity usage, solar production, and cost."""

    day: date
    consumption_kwh: float
    production_kwh: float
    cost_gross: float
    is_final: bool

    @classmethod
    def from_dict(cls, d: dict) -> UsageDay:
        """Parse one usageCostsPerPeriod entry."""
        return cls(
            day=_dt(d["periodFrom"]).date(),
            consumption_kwh=_num(_nested(d, "usageElectricityConsumption", "rawUsage"))
            or 0.0,
            production_kwh=_num(_nested(d, "usageElectricityProduction", "rawUsage"))
            or 0.0,
            cost_gross=_num(_nested(d, "totalCosts", "totalRawCosts", "amountGross"))
            or 0.0,
            is_final=bool(_nested(d, "usageElectricityConsumption", "isFinal")),
        )


def usage_days_from_details(payload: dict) -> list[UsageDay]:
    """Flatten overviewPeriods[].usageCostsPerPeriod[] into sorted UsageDays."""
    days: list[UsageDay] = []
    for overview in payload.get("overviewPeriods") or []:
        for p in overview.get("usageCostsPerPeriod") or []:
            try:
                days.append(UsageDay.from_dict(p))
            except (KeyError, ValueError):
                continue
    days.sort(key=lambda x: x.day)
    return days


@dataclass(slots=True)
class UsageSummary:
    """Per-day usage rows plus month-to-date aggregates."""

    latest: UsageDay | None  # most recent (final) day, i.e. "yesterday"
    mtd_consumption: float
    mtd_production: float
    mtd_cost: float
    days: list[UsageDay] = field(default_factory=list)

    @classmethod
    def from_days(cls, days: list[UsageDay]) -> UsageSummary:
        """Aggregate sorted UsageDays into a summary."""
        final = [d for d in days if d.is_final] or days
        return cls(
            latest=final[-1] if final else None,
            mtd_consumption=round(sum(d.consumption_kwh for d in days), 3),
            mtd_production=round(sum(d.production_kwh for d in days), 3),
            mtd_cost=round(sum(d.cost_gross for d in days), 2),
            days=days,
        )


@dataclass(slots=True)
class FreeEnergyPeriod:
    """A scheduled free-energy window."""

    start: datetime
    end: datetime


@dataclass(slots=True)
class FreeEnergyStatus:
    """Free-energy eligibility, current activation, and upcoming windows."""

    eligible: bool
    active: bool
    periods: list[FreeEnergyPeriod] = field(default_factory=list)

    @property
    def next_period(self) -> FreeEnergyPeriod | None:
        """The earliest upcoming window, if any."""
        return self.periods[0] if self.periods else None

    @classmethod
    def from_dict(cls, d: dict) -> FreeEnergyStatus:
        """Parse the freeEnergy status response."""
        periods: list[FreeEnergyPeriod] = []
        for p in d.get("nextFreeEnergyPeriods") or []:
            start, end = _dt_aware(p.get("from")), _dt_aware(p.get("until"))
            if start and end:
                periods.append(FreeEnergyPeriod(start, end))
        periods.sort(key=lambda x: x.start)
        return cls(
            eligible=bool(d.get("isFreeEnergyEligible")),
            active=bool(d.get("isFreeEnergyActive")),
            periods=periods,
        )


@dataclass(slots=True)
class ContractInfo:
    """Contract metadata from the contract-info endpoint."""

    contract_type: str | None
    start_date: datetime | None
    standing_charge: float | None  # fixedElecTariff (fixed supply cost)

    @classmethod
    def from_dict(cls, d: dict) -> ContractInfo:
        """Parse the contract-info response."""
        return cls(
            contract_type=d.get("contractType"),
            start_date=_dt_aware(d.get("contractStartDate")),
            standing_charge=_num(d.get("fixedElecTariff")),
        )


@dataclass(slots=True)
class Mandate:
    """Daily meter-reading mandate and allocation status."""

    mandate: str | None
    allocation: str | None

    @classmethod
    def from_dict(cls, d: dict) -> Mandate:
        """Parse the dailyReading mandate response."""
        return cls(mandate=d.get("mandate"), allocation=d.get("allocation"))


@dataclass(slots=True)
class Tokens:
    """OAuth2 token pair with its absolute expiry."""

    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds

    @classmethod
    def from_payload(cls, payload: dict, now: float) -> Tokens:
        """Build from a /connect/token response, anchoring expiry to `now`."""
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token", ""),
            expires_at=now + float(payload.get("expires_in", 3600)),
        )
