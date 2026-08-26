# aiobudgetthuis

Async Python client for the **unofficial** Budget Thuis (Budget Energie) API: hourly dynamic
electricity prices, daily usage/solar production/cost, monthly installment, free-energy
windows, and contract discovery.

> **Unaffiliated.** This project is not affiliated with, endorsed by, or supported by
> Budget Thuis / Budget Energie. The API is not publicly documented and may change or
> break at any time. "Budget Thuis" is a trademark of its respective owner.

Built for the [ha-budget-thuis](https://github.com/jdolieslager/ha-budget-thuis) Home
Assistant integration, but usable standalone in any asyncio application.

## Install

```bash
pip install aiobudgetthuis
```

Requires Python 3.12+ and an `aiohttp` session managed by you.

## Usage

```python
import aiohttp

from aiobudgetthuis import BudgetThuisClient


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        client = BudgetThuisClient(session)

        # Login replays the server-rendered OAuth2 + PKCE form. Store only the
        # refresh token; never persist the password.
        tokens = await client.login("user@example.com", "password")

        contracts = await client.async_get_contracts(tokens.access_token)
        contract = next(c for c in contracts if c.is_active)

        from datetime import datetime, timedelta

        now = datetime.now().astimezone()
        details = await client.hourly_tariff(
            tokens.access_token, contract.id, now, now + timedelta(days=1)
        )
        for day in details.days:
            for tariff in day.electricity:
                print(tariff.period_from, tariff.total.gross)
```

Later sessions authenticate with `await client.refresh(refresh_token)`.

### API surface

- `login(username, password)` / `refresh(refresh_token)` → `Tokens`
- `async_get_contracts(access_token)` → `list[Contract]`
- `hourly_tariff(...)` → `HourlyTariffDetails` (wrap in `PriceData` for derived values:
  current/next slot, daily min/max/average, forecast attributes)
- `usage_summary(...)` → `UsageSummary` (per-day usage, solar production, cost, month-to-date)
- `monthly_amount(...)` → `MonthlyAmount` (installment)
- `free_energy_status(...)` → `FreeEnergyStatus`
- `contract_info(...)` → `ContractInfo`
- `daily_reading_mandate(...)` → `Mandate`

Errors: `BudgetThuisAuthError` (bad credentials / refused token) and
`BudgetThuisConnectionError` (network / unexpected upstream response), both subclasses of
`BudgetThuisError`.

## Related projects

- [`ha-budget-thuis`](https://github.com/jdolieslager/ha-budget-thuis) — Home Assistant (HACS) integration built on this client.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy src && pytest -q
```

## License

MIT
