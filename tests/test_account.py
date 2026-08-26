"""Tests for account/usage model parsing."""

from aiobudgetthuis.models import (
    ContractInfo,
    FreeEnergyStatus,
    Mandate,
    MonthlyAmount,
    UsageSummary,
    usage_days_from_details,
)


def test_monthly_amount():
    m = MonthlyAmount.from_dict(
        {
            "currentAdvanceAmount": {
                "amountNet": 57.01,
                "amountVat": 11.99,
                "amountGross": 69,
            },
            "minimumAdvanceAmount": 35,
            "maximumAdvanceAmount": 207,
        }
    )
    assert m.current_gross == 69.0
    assert m.minimum == 35.0
    assert m.maximum == 207.0


DETAILS = {
    "overviewPeriods": [
        {
            "usageCostsPerPeriod": [
                {
                    "usageElectricityConsumption": {"rawUsage": 9.631, "isFinal": True},
                    "usageElectricityProduction": {"rawUsage": 15.77, "isFinal": True},
                    "totalCosts": {"totalRawCosts": {"amountGross": -0.724527}},
                    "periodFrom": "2026-08-01T00:00:00+02:00",
                    "periodTo": "2026-08-02T00:00:00+02:00",
                },
                {
                    "usageElectricityConsumption": {
                        "rawUsage": 11.467,
                        "isFinal": True,
                    },
                    "usageElectricityProduction": {"rawUsage": 14.743, "isFinal": True},
                    "totalCosts": {"totalRawCosts": {"amountGross": 0.726934}},
                    "periodFrom": "2026-08-02T00:00:00+02:00",
                    "periodTo": "2026-08-03T00:00:00+02:00",
                },
            ]
        }
    ]
}


def test_usage_summary_mtd_and_latest():
    s = UsageSummary.from_days(usage_days_from_details(DETAILS))
    assert round(s.mtd_consumption, 3) == round(9.631 + 11.467, 3)
    assert round(s.mtd_production, 3) == round(15.77 + 14.743, 3)
    assert round(s.mtd_cost, 2) == round(-0.724527 + 0.726934, 2)
    # latest = most recent day
    assert s.latest is not None
    assert s.latest.consumption_kwh == 11.467


def test_free_energy_status():
    fe = FreeEnergyStatus.from_dict(
        {
            "isFreeEnergyEligible": False,
            "isFreeEnergyActive": False,
            "nextFreeEnergyPeriods": [
                {
                    "from": "2026-08-29T12:00:00+02:00",
                    "until": "2026-08-29T17:00:00+02:00",
                },
                {
                    "from": "2026-08-30T12:00:00+02:00",
                    "until": "2026-08-30T17:00:00+02:00",
                },
            ],
        }
    )
    assert fe.eligible is False
    assert fe.active is False
    assert len(fe.periods) == 2
    assert fe.next_period.start.hour == 12


def test_contract_info_naive_start_gets_tz():
    ci = ContractInfo.from_dict(
        {
            "contractType": "Dynamic",
            "contractStartDate": "2026-01-27T00:00:00",
            "fixedElecTariff": 5.99,
        }
    )
    assert ci.contract_type == "Dynamic"
    assert ci.standing_charge == 5.99
    assert ci.start_date is not None
    assert ci.start_date.tzinfo is not None  # tz attached


def test_mandate():
    m = Mandate.from_dict({"mandate": "Active", "allocation": "Active"})
    assert m.mandate == "Active"
    assert m.allocation == "Active"
