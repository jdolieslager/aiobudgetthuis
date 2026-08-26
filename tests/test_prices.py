"""Unit tests for the client's parsing + price math (no HA needed)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiobudgetthuis.models import HourlyTariffDetails
from aiobudgetthuis.prices import PRICE_GROSS, PRICE_NET, PriceData

TZ = ZoneInfo("Europe/Amsterdam")

SAMPLE = {
    "tariffDays": [
        {
            "tariffsOfDate": "2026-08-26T00:00:00+02:00",
            "reasonNoTariffs": "Unknown",
            "electricityTariffs": [
                {
                    "totalTariff": {
                        "amountNet": 0.27,
                        "amountVat": 0.057,
                        "amountGross": 0.32755,
                    },
                    "commodity": {
                        "amountNet": 0.165,
                        "amountVat": 0.035,
                        "amountGross": 0.19988,
                    },
                    "energyTax": {
                        "amountNet": 0.0916,
                        "amountVat": 0.0192,
                        "amountGross": 0.11085,
                    },
                    "surcharge": {
                        "amountNet": 0.0139,
                        "amountVat": 0.0029,
                        "amountGross": 0.01682,
                    },
                    "periodFrom": "2026-08-26T00:00:00+02:00",
                    "periodTo": "2026-08-26T01:00:00+02:00",
                },
                {
                    "totalTariff": {
                        "amountNet": 0.12,
                        "amountVat": 0.025,
                        "amountGross": 0.14500,
                    },
                    "commodity": {
                        "amountNet": 0.02,
                        "amountVat": 0.004,
                        "amountGross": 0.024,
                    },
                    "energyTax": {
                        "amountNet": 0.0916,
                        "amountVat": 0.0192,
                        "amountGross": 0.11085,
                    },
                    "surcharge": {
                        "amountNet": 0.0139,
                        "amountVat": 0.0029,
                        "amountGross": 0.01682,
                    },
                    "periodFrom": "2026-08-26T12:00:00+02:00",
                    "periodTo": "2026-08-26T13:00:00+02:00",
                },
            ],
            "gasTariffs": [],
        }
    ]
}


def _data(price_type=PRICE_GROSS) -> PriceData:
    return PriceData(HourlyTariffDetails.from_dict(SAMPLE), price_type)


def test_parses_and_sorts_slots():
    pd = _data()
    assert len(pd.slots) == 2
    assert pd.slots[0].start < pd.slots[1].start


def test_current_slot_and_components():
    pd = _data()
    now = datetime(2026, 8, 26, 12, 30, tzinfo=TZ)
    assert abs(pd.current_slot(now).price - 0.145) < 1e-9
    t = pd.current_tariff(now)
    assert t.commodity.gross == 0.024
    assert t.energy_tax.gross == 0.11085


def test_daily_aggregates():
    pd = _data()
    now = datetime(2026, 8, 26, 12, 30, tzinfo=TZ)
    assert pd.lowest_today(now).price == 0.145
    assert pd.highest_today(now).price == 0.32755
    assert pd.lowest_today(now).start.hour == 12
    assert round(pd.average_today(now), 5) == round((0.32755 + 0.145) / 2, 5)
    assert pd.percentage_of_max(now) == round(0.145 / 0.32755 * 100, 1)


def test_net_price_type_differs():
    now = datetime(2026, 8, 26, 12, 30, tzinfo=TZ)
    assert _data(PRICE_NET).current_slot(now).price == 0.12


def test_forecast_attributes():
    pd = _data()
    now = datetime(2026, 8, 26, 12, 30, tzinfo=TZ)
    assert len(pd.prices_for(now.date())) == 2
    assert pd.tomorrow_valid(now) is False
