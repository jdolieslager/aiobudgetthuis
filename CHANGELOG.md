# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-26

### Added

- Initial release of `aiobudgetthuis`, an async client for the unofficial
  Budget Thuis (Budget Energie) API.
- OAuth2 Authorization Code + PKCE login via server-rendered form replay, and
  refresh-token exchange (`login`, `refresh`).
- Contract discovery (`async_get_contracts`).
- Data endpoints: hourly dynamic tariffs (`hourly_tariff`), daily usage /
  solar production / cost (`usage_summary`), monthly installment
  (`monthly_amount`), free-energy windows (`free_energy_status`), contract
  metadata (`contract_info`), and the daily meter-reading mandate
  (`daily_reading_mandate`).
- `PriceData` helper with derived values: current/next slot, daily
  min/max/average, and forecast attributes.
- Error hierarchy: `BudgetThuisError` with `BudgetThuisAuthError` and
  `BudgetThuisConnectionError`; all failures (network, timeouts, malformed
  payloads) surface as package error types.

[0.1.0]: https://github.com/jdolieslager/aiobudgetthuis/releases/tag/v0.1.0
