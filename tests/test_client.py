"""Client tests against a local aiohttp fake of the accounts + data APIs.

All hostnames, tokens, ids, and payloads are fictional. The fake replays just
enough of the OAuth2 form flow and the data endpoints to exercise
BudgetThuisClient end to end, including its error mapping.
"""

import asyncio
from datetime import UTC, datetime
import time

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import pytest

from aiobudgetthuis import (
    BudgetThuisAuthError,
    BudgetThuisClient,
    BudgetThuisConnectionError,
)

ANTIFORGERY = "fictional-antiforgery-token"
AUTH_CODE = "fictional-auth-code"
ACCESS_TOKEN = "fictional-access-token"
REFRESH_TOKEN = "fictional-refresh-token"
RETURN_URL = "/connect/authorize/callback?state=fic"
LOGIN_LOCATION = "/inloggen?ReturnUrl=%2Fconnect%2Fauthorize%2Fcallback%3Fstate%3Dfic"


class FakeBudgetThuis:
    """Configurable fake for both the accounts host and the data API host."""

    def __init__(self):
        # Scenario knobs, mutated by tests before the client call.
        self.omit_return_url = False
        self.omit_antiforgery = False
        self.reject_credentials = False
        self.omit_code = False
        self.token_status = 200
        self.token_payload = {
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "expires_in": 900,
            "token_type": "Bearer",
        }
        self.data_status = 200
        self.data_payload = {}
        self.data_broken_json = False
        self.data_delay = 0.0
        self.contact_person_payload = {
            "contactPerson": {
                "customers": [{"productCustomers": [{"productCustomerId": 12345}]}]
            }
        }
        self.product_picker_payload = {
            "contractsInfo": [
                {
                    "contractId": 67890,
                    "contractStatus": "Active",
                    "contractType": "Dynamic",
                    "supplyAddress": {
                        "street": "Voorbeeldstraat",
                        "houseNumber": 1,
                        "city": "Voorbeeldstad",
                    },
                }
            ]
        }
        # Recorded requests, asserted by tests after the client call.
        self.token_requests = []
        self.product_picker_requests = []
        self.last_data_headers = None

        self.app = web.Application()
        self.app.router.add_get("/connect/authorize", self._authorize)
        self.app.router.add_get("/inloggen", self._login_page)
        self.app.router.add_post("/inloggen", self._login_submit)
        self.app.router.add_get("/connect/authorize/callback", self._callback)
        self.app.router.add_post("/connect/token", self._token)
        self.app.router.add_get("/home/v1/contactPerson", self._contact_person)
        self.app.router.add_post(
            "/energy/v2/customer/productPicker", self._product_picker
        )
        self.app.router.add_get("/{tail:.+}", self._data)

    async def _authorize(self, request):
        location = "/inloggen" if self.omit_return_url else LOGIN_LOCATION
        return web.Response(status=302, headers={"Location": location})

    async def _login_page(self, request):
        field = (
            ""
            if self.omit_antiforgery
            else f'<input name="__RequestVerificationToken" value="{ANTIFORGERY}"/>'
        )
        return web.Response(text=f"<form>{field}</form>", content_type="text/html")

    async def _login_submit(self, request):
        form = await request.post()
        assert form["__RequestVerificationToken"] == ANTIFORGERY
        assert form["ReturnUrl"] == RETURN_URL
        if self.reject_credentials:
            return web.Response(text="<form>try again</form>")
        return web.Response(status=302, headers={"Location": RETURN_URL})

    async def _callback(self, request):
        query = "" if self.omit_code else f"?code={AUTH_CODE}"
        return web.Response(
            status=302,
            headers={"Location": f"budgetthuis://login_success{query}"},
        )

    async def _token(self, request):
        self.token_requests.append(dict(await request.post()))
        if self.token_status != 200:
            return web.json_response(
                {"error": "invalid_grant"}, status=self.token_status
            )
        return web.json_response(self.token_payload)

    async def _contact_person(self, request):
        return web.json_response(self.contact_person_payload)

    async def _product_picker(self, request):
        self.product_picker_requests.append(await request.json())
        return web.json_response(self.product_picker_payload)

    async def _data(self, request):
        if self.data_delay:
            await asyncio.sleep(self.data_delay)
        self.last_data_headers = dict(request.headers)
        if self.data_broken_json:
            return web.Response(text='{"broken":', content_type="application/json")
        return web.json_response(self.data_payload, status=self.data_status)


@pytest.fixture
async def fake():
    fake = FakeBudgetThuis()
    server = TestServer(fake.app)
    await server.start_server()
    fake.url = str(server.make_url("/")).rstrip("/")
    yield fake
    await server.close()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


@pytest.fixture
def client(fake, session):
    return BudgetThuisClient(session, accounts_url=fake.url, api_url=fake.url)


# -- login --------------------------------------------------------------------


async def test_login_happy_path(fake, client):
    before = time.time()
    tokens = await client.login("user@example.com", "fictional-password")

    assert tokens.access_token == ACCESS_TOKEN
    assert tokens.refresh_token == REFRESH_TOKEN
    assert before + 890 <= tokens.expires_at <= time.time() + 900

    (req,) = fake.token_requests
    assert req["grant_type"] == "authorization_code"
    assert req["code"] == AUTH_CODE
    assert req["code_verifier"]


async def test_login_wrong_credentials(fake, client):
    fake.reject_credentials = True
    with pytest.raises(BudgetThuisAuthError):
        await client.login("user@example.com", "wrong-password")


async def test_login_missing_return_url(fake, client):
    fake.omit_return_url = True
    with pytest.raises(BudgetThuisConnectionError):
        await client.login("user@example.com", "fictional-password")


async def test_login_missing_antiforgery_token(fake, client):
    fake.omit_antiforgery = True
    with pytest.raises(BudgetThuisConnectionError):
        await client.login("user@example.com", "fictional-password")


async def test_login_missing_auth_code(fake, client):
    fake.omit_code = True
    with pytest.raises(BudgetThuisAuthError):
        await client.login("user@example.com", "fictional-password")


async def test_login_unreachable_host(session):
    # Nothing listens on this port; the connection error must be wrapped.
    client = BudgetThuisClient(
        session,
        accounts_url="http://127.0.0.1:1",
        api_url="http://127.0.0.1:1",
    )
    with pytest.raises(BudgetThuisConnectionError):
        await client.login("user@example.com", "fictional-password")


# -- token refresh ------------------------------------------------------------


async def test_refresh_happy_path(fake, client):
    tokens = await client.refresh("old-fictional-refresh-token")
    assert tokens.access_token == ACCESS_TOKEN
    assert tokens.refresh_token == REFRESH_TOKEN
    (req,) = fake.token_requests
    assert req["grant_type"] == "refresh_token"
    assert req["refresh_token"] == "old-fictional-refresh-token"


async def test_refresh_keeps_token_when_server_does_not_rotate(fake, client):
    del fake.token_payload["refresh_token"]
    tokens = await client.refresh("old-fictional-refresh-token")
    assert tokens.refresh_token == "old-fictional-refresh-token"


async def test_refresh_rejected_token(fake, client):
    fake.token_status = 400
    with pytest.raises(BudgetThuisAuthError):
        await client.refresh("expired-fictional-refresh-token")


async def test_token_payload_missing_access_token(fake, client):
    fake.token_payload = {"token_type": "Bearer"}
    with pytest.raises(BudgetThuisConnectionError):
        await client.refresh("old-fictional-refresh-token")


# -- contract discovery -------------------------------------------------------


async def test_get_contracts(fake, client):
    contracts = await client.async_get_contracts(ACCESS_TOKEN)

    assert fake.product_picker_requests == [{"relationIds": [12345]}]
    (contract,) = contracts
    assert contract.id == "67890"
    assert contract.is_active
    assert contract.label == "Voorbeeldstraat 1, Voorbeeldstad - Dynamic"


async def test_get_contracts_without_relations(fake, client):
    fake.contact_person_payload = {"contactPerson": {"customers": []}}
    assert await client.async_get_contracts(ACCESS_TOKEN) == []
    assert fake.product_picker_requests == []


async def test_get_contracts_malformed_contact_person(fake, client):
    fake.contact_person_payload = ["not", "a", "dict"]
    with pytest.raises(BudgetThuisConnectionError):
        await client.async_get_contracts(ACCESS_TOKEN)


# -- data endpoints: status/error mapping --------------------------------------


async def test_data_call_sends_bearer_and_parses(fake, client):
    fake.data_payload = {
        "currentAdvanceAmount": {"amountGross": 150.0},
        "minimumAdvanceAmount": 100,
        "maximumAdvanceAmount": 250,
    }
    amount = await client.monthly_amount(ACCESS_TOKEN, "67890")
    assert amount.current_gross == 150.0
    assert amount.minimum == 100.0
    assert amount.maximum == 250.0
    assert fake.last_data_headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"


@pytest.mark.parametrize("status", [401, 403])
async def test_data_unauthorized_maps_to_auth_error(fake, client, status):
    fake.data_status = status
    with pytest.raises(BudgetThuisAuthError):
        await client.monthly_amount(ACCESS_TOKEN, "67890")


async def test_data_server_error_maps_to_connection_error(fake, client):
    fake.data_status = 500
    with pytest.raises(BudgetThuisConnectionError):
        await client.monthly_amount(ACCESS_TOKEN, "67890")


async def test_data_broken_json(fake, client):
    fake.data_broken_json = True
    with pytest.raises(BudgetThuisConnectionError):
        await client.monthly_amount(ACCESS_TOKEN, "67890")


async def test_data_non_dict_payload(fake, client):
    fake.data_payload = ["not", "a", "dict"]
    with pytest.raises(BudgetThuisConnectionError):
        await client.monthly_amount(ACCESS_TOKEN, "67890")


async def test_data_timeout(fake):
    fake.data_delay = 5.0
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=0.25)
    ) as session:
        client = BudgetThuisClient(session, accounts_url=fake.url, api_url=fake.url)
        with pytest.raises(BudgetThuisConnectionError):
            await client.monthly_amount(ACCESS_TOKEN, "67890")


async def test_hourly_tariff_malformed_payload(fake, client):
    # A tariffDays entry without its required date must become a package error.
    fake.data_payload = {"tariffDays": [{"electricityTariffs": []}]}
    now = datetime.now(UTC)
    with pytest.raises(BudgetThuisConnectionError):
        await client.hourly_tariff(ACCESS_TOKEN, "67890", now, now)


async def test_hourly_tariff_happy_path(fake, client):
    fake.data_payload = {
        "tariffDays": [
            {
                "tariffsOfDate": "2026-08-26T00:00:00+02:00",
                "electricityTariffs": [
                    {
                        "totalTariff": {
                            "amountNet": 0.20,
                            "amountVat": 0.042,
                            "amountGross": 0.242,
                        },
                        "periodFrom": "2026-08-26T00:00:00+02:00",
                        "periodTo": "2026-08-26T01:00:00+02:00",
                    }
                ],
            }
        ]
    }
    now = datetime.now(UTC)
    details = await client.hourly_tariff(ACCESS_TOKEN, "67890", now, now)
    (day,) = details.days
    (tariff,) = day.electricity
    assert tariff.total.gross == 0.242
