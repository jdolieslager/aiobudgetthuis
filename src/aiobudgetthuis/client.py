"""Async Budget Thuis API client (aiohttp).

Implements OAuth2 Authorization Code + PKCE via server-rendered form replay,
token refresh, and the data endpoints. The login uses its own cookie-jar
session (CSRF cookie); refresh and data calls use the injected shared session.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from typing import TYPE_CHECKING, cast
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import aiohttp

from .models import (
    Contract,
    ContractInfo,
    FreeEnergyStatus,
    HourlyTariffDetails,
    Mandate,
    MonthlyAmount,
    Tokens,
    UsageSummary,
    relation_ids_from_contact_person,
    usage_days_from_details,
)

if TYPE_CHECKING:
    from datetime import datetime

CLIENT_ID = "mobile"
REDIRECT_URI = "budgetthuis://login_success"
SCOPE = "mobileApi webApi offline_access openid email idsServiceExternal"
LABEL = "BudgetEnergie"
USER_AGENT = (
    "Budget Thuis/3.1.0 (nl.budgetthuis.app; build:2940; iOS 26.6.0) Alamofire/5.10.2"
)
DEFAULT_ACCOUNTS_URL = "https://accounts.budgetthuis.nl"
DEFAULT_API_URL = "https://app.api.nutsservices.nl"

_TZ = ZoneInfo("Europe/Amsterdam")
_PERIOD_FMT = "%Y-%m-%dT%H:%M:%S.000"
_ANTIFORGERY_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_REDIRECTS = (301, 302, 303, 307, 308)
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_HTTP_OK = 200


class BudgetThuisError(Exception):
    """Base error."""


class BudgetThuisAuthError(BudgetThuisError):
    """Invalid credentials or refused/expired token."""


class BudgetThuisConnectionError(BudgetThuisError):
    """Network / unexpected upstream response."""


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _qp(url: str, key: str) -> str | None:
    values = parse_qs(urlparse(url).query).get(key)
    return values[0] if values else None


class BudgetThuisClient:
    """Client for the accounts (auth) and data APIs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        accounts_url: str = DEFAULT_ACCOUNTS_URL,
        api_url: str = DEFAULT_API_URL,
    ) -> None:
        """Wrap a caller-managed session; URLs are overridable for testing."""
        self._session = session
        self._accounts = accounts_url.rstrip("/")
        self._api = api_url.rstrip("/")

    async def login(self, username: str, password: str) -> Tokens:
        """Full PKCE form-replay login. Uses an isolated cookie-jar session."""
        verifier, challenge = _pkce()
        headers = {"User-Agent": USER_AGENT}
        try:
            async with aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(), headers=headers, timeout=_TIMEOUT
            ) as s:
                # 1. authorize -> 302 /inloggen?ReturnUrl=...
                async with s.get(
                    f"{self._accounts}/connect/authorize",
                    params={
                        "client_id": CLIENT_ID,
                        "response_type": "code",
                        "redirect_uri": REDIRECT_URI,
                        "scope": SCOPE,
                        "label": LABEL,
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                    },
                    allow_redirects=False,
                ) as r:
                    login_loc = self._location(r, "authorize")
                return_url = _qp(login_loc, "ReturnUrl")
                if not return_url:
                    raise BudgetThuisConnectionError("authorize: no ReturnUrl")

                # 2. login page -> antiforgery token
                async with s.get(
                    urljoin(self._accounts, login_loc), allow_redirects=False
                ) as r:
                    html = await r.text()
                m = _ANTIFORGERY_RE.search(html)
                if not m:
                    raise BudgetThuisConnectionError(
                        "login page: no verification token"
                    )

                # 3. submit creds -> 302 (200 = wrong credentials)
                async with s.post(
                    f"{self._accounts}/inloggen",
                    data={
                        "Username": username,
                        "Password": password,
                        "ReturnUrl": return_url,
                        "Label": LABEL,
                        "__RequestVerificationToken": m.group(1),
                        "button": "login",
                    },
                    allow_redirects=False,
                ) as r:
                    if r.status not in _REDIRECTS:
                        raise BudgetThuisAuthError("invalid credentials")
                    callback = self._location(r, "login")

                # 4. callback -> 302 budgetthuis://login_success?code=...
                async with s.get(
                    urljoin(self._accounts, callback), allow_redirects=False
                ) as r:
                    redirect = self._location(r, "callback")
                code = _qp(redirect, "code")
                if not code:
                    raise BudgetThuisAuthError("no authorization code")

                # 5. exchange code for tokens
                return await self._token_request(
                    s,
                    {
                        "grant_type": "authorization_code",
                        "code": code,
                        "code_verifier": verifier,
                        "redirect_uri": REDIRECT_URI,
                        "client_id": CLIENT_ID,
                    },
                )
        except aiohttp.ClientError as err:
            raise BudgetThuisConnectionError(str(err)) from err

    async def refresh(self, refresh_token: str) -> Tokens:
        """Exchange a refresh token for a fresh token pair."""
        try:
            tokens = await self._token_request(
                self._session,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CLIENT_ID,
                },
            )
        except aiohttp.ClientError as err:
            raise BudgetThuisConnectionError(str(err)) from err
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token  # server may not rotate
        return tokens

    async def async_get_contracts(self, access_token: str) -> list[Contract]:
        """Discover the account's contracts (no id needed in the path).

        contactPerson -> relation ids -> productPicker -> contractsInfo.
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        try:
            async with self._session.get(
                f"{self._api}/home/v1/contactPerson", headers=headers
            ) as r:
                if r.status in (401, 403):
                    raise BudgetThuisAuthError(f"contactPerson: status {r.status}")
                if r.status != _HTTP_OK:
                    raise BudgetThuisConnectionError(
                        f"contactPerson: status {r.status}"
                    )
                relation_ids = relation_ids_from_contact_person(await r.json())

            if not relation_ids:
                return []

            async with self._session.post(
                f"{self._api}/energy/v2/customer/productPicker",
                json={"relationIds": relation_ids},
                headers=headers,
            ) as r:
                if r.status in (401, 403):
                    raise BudgetThuisAuthError(f"productPicker: status {r.status}")
                if r.status != _HTTP_OK:
                    raise BudgetThuisConnectionError(
                        f"productPicker: status {r.status}"
                    )
                data = await r.json()
        except aiohttp.ClientError as err:
            raise BudgetThuisConnectionError(str(err)) from err

        return [Contract.from_dict(c) for c in data.get("contractsInfo", [])]

    async def _get_json(
        self, access_token: str, path: str, params: dict | None = None
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        try:
            async with self._session.get(
                f"{self._api}{path}", params=params, headers=headers
            ) as r:
                if r.status in (401, 403):
                    raise BudgetThuisAuthError(f"{path}: status {r.status}")
                if r.status != _HTTP_OK:
                    raise BudgetThuisConnectionError(f"{path}: status {r.status}")
                return cast("dict", await r.json())
        except aiohttp.ClientError as err:
            raise BudgetThuisConnectionError(str(err)) from err

    async def hourly_tariff(
        self,
        access_token: str,
        contract_id: str,
        period_from: datetime,
        period_to: datetime,
    ) -> HourlyTariffDetails:
        """Fetch hourly electricity tariffs for the given period."""
        data = await self._get_json(
            access_token,
            f"/energy/v2/contract/{contract_id}/hourlytariff/details",
            {
                "AddDayBeforeDayAfter": "false",
                "PeriodFrom": period_from.astimezone(_TZ).strftime(_PERIOD_FMT),
                "PeriodTo": period_to.astimezone(_TZ).strftime(_PERIOD_FMT),
            },
        )
        return HourlyTariffDetails.from_dict(data)

    async def monthly_amount(
        self, access_token: str, contract_id: str
    ) -> MonthlyAmount:
        """Fetch the monthly installment and its adjustment range."""
        data = await self._get_json(
            access_token, f"/energy/v2/contract/{contract_id}/monthlyAmount"
        )
        return MonthlyAmount.from_dict(data)

    async def usage_summary(
        self,
        access_token: str,
        contract_id: str,
        period_from: datetime,
        period_to: datetime,
    ) -> UsageSummary:
        """Fetch per-day usage/production/cost for the period, aggregated."""
        data = await self._get_json(
            access_token,
            f"/energy/v1/contract/{contract_id}/usagecosts/details",
            {
                "PeriodDuration": "Day",
                "PeriodFrom": period_from.astimezone(_TZ).strftime(_PERIOD_FMT),
                "PeriodTo": period_to.astimezone(_TZ).strftime(_PERIOD_FMT),
            },
        )
        return UsageSummary.from_days(usage_days_from_details(data))

    async def free_energy_status(
        self, access_token: str, contract_id: str
    ) -> FreeEnergyStatus:
        """Fetch free-energy eligibility and upcoming windows."""
        data = await self._get_json(
            access_token, f"/energy/v2/freeEnergy/{contract_id}/status"
        )
        return FreeEnergyStatus.from_dict(data)

    async def contract_info(self, access_token: str, contract_id: str) -> ContractInfo:
        """Fetch contract metadata (type, start date, standing charge)."""
        data = await self._get_json(
            access_token, f"/energy/v1/customer/{contract_id}/contract-info"
        )
        return ContractInfo.from_dict(data)

    async def daily_reading_mandate(
        self, access_token: str, contract_id: str
    ) -> Mandate:
        """Fetch the daily meter-reading mandate status."""
        data = await self._get_json(
            access_token, f"/energy/v2/dailyReading/mandate/{contract_id}"
        )
        return Mandate.from_dict(data)

    # -- helpers ------------------------------------------------------------
    async def _token_request(
        self, session: aiohttp.ClientSession, data: dict
    ) -> Tokens:
        async with session.post(
            f"{self._accounts}/connect/token",
            data=data,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=False,
        ) as r:
            if r.status in (400, 401, 403):
                raise BudgetThuisAuthError(f"token: status {r.status}")
            if r.status != _HTTP_OK:
                raise BudgetThuisConnectionError(f"token: status {r.status}")
            payload = await r.json()
        return Tokens.from_payload(payload, time.time())

    @staticmethod
    def _location(response: aiohttp.ClientResponse, step: str) -> str:
        if response.status not in _REDIRECTS:
            raise BudgetThuisConnectionError(
                f"{step}: expected redirect, got {response.status}"
            )
        loc = response.headers.get("Location")
        if not loc:
            raise BudgetThuisConnectionError(f"{step}: redirect without Location")
        return loc
