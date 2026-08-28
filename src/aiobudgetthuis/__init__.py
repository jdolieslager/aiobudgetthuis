"""Async client for the unofficial Budget Thuis (Budget Energie) API.

Not affiliated with Budget Thuis; the API may change without notice.
Authentication is OAuth2 Authorization Code + PKCE replayed against the
server-rendered login form; persist only the refresh token.
"""

from __future__ import annotations

from .client import (
    BudgetThuisAuthError,
    BudgetThuisClient,
    BudgetThuisConnectionError,
    BudgetThuisError,
)
from .models import (
    Contract,
    ContractInfo,
    FreeEnergyStatus,
    HourlyTariffDetails,
    Mandate,
    MonthlyAmount,
    Tokens,
    UsageDay,
    UsageSummary,
)
from .prices import PRICE_GROSS, PRICE_NET, PriceData, PriceSlot

__version__ = "0.1.1"

__all__ = [
    "PRICE_GROSS",
    "PRICE_NET",
    "BudgetThuisAuthError",
    "BudgetThuisClient",
    "BudgetThuisConnectionError",
    "BudgetThuisError",
    "Contract",
    "ContractInfo",
    "FreeEnergyStatus",
    "HourlyTariffDetails",
    "Mandate",
    "MonthlyAmount",
    "PriceData",
    "PriceSlot",
    "Tokens",
    "UsageDay",
    "UsageSummary",
]
