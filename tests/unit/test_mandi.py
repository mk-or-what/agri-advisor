import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from advisor.clients.mandi import RESOURCE_URL, get_latest_prices
from advisor.config import get_settings
from advisor.errors import DataUnavailableError, SchemaMismatchError, UpstreamTimeoutError

FIXTURES = Path(__file__).parent.parent / "fixtures"
FAKE_KEY = "test-key-not-real"
EMPTY = {"records": []}


def load_payload() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / "mandi_onion_nashik.json").read_text())
    return payload


@pytest.fixture(autouse=True)
def api_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test a fake key so no test depends on your real .env file."""
    monkeypatch.setenv("DATA_GOV_IN_API_KEY", FAKE_KEY)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@respx.mock
async def test_market_scope_matches_names_despite_stray_spaces() -> None:
    respx.get(RESOURCE_URL).mock(return_value=httpx.Response(200, json=load_payload()))

    result = await get_latest_prices("Maharashtra", "Onion", "Nashik", "APMC Nasik")

    prices = result.value.prices
    assert result.value.scope == "market"
    assert prices
    assert all(p.market == "APMC Nasik" for p in prices)
    dates = [p.arrival_date for p in prices]
    assert dates == sorted(dates, reverse=True)
    assert result.unit == "INR per quintal"
    assert "Agmarknet" in result.source


@respx.mock
async def test_limit_caps_the_number_of_prices() -> None:
    respx.get(RESOURCE_URL).mock(return_value=httpx.Response(200, json=load_payload()))

    result = await get_latest_prices("Maharashtra", "Onion", "Nashik", "APMC Nasik", limit=2)

    assert len(result.value.prices) == 2


@respx.mock
async def test_unknown_market_falls_back_to_district() -> None:
    respx.get(RESOURCE_URL).mock(return_value=httpx.Response(200, json=load_payload()))

    result = await get_latest_prices("Maharashtra", "Onion", "Nashik", "No Such Mandi")

    assert result.value.scope == "district"
    assert result.value.prices


@respx.mock
async def test_empty_district_falls_back_to_state() -> None:
    respx.get(RESOURCE_URL).mock(
        side_effect=[
            httpx.Response(200, json=EMPTY),
            httpx.Response(200, json=load_payload()),
        ]
    )

    result = await get_latest_prices("Maharashtra", "Onion", "Nashik")

    assert result.value.scope == "state"
    assert result.value.prices


@respx.mock
async def test_nothing_found_raises_data_unavailable() -> None:
    respx.get(RESOURCE_URL).mock(return_value=httpx.Response(200, json=EMPTY))

    with pytest.raises(DataUnavailableError):
        await get_latest_prices("Maharashtra", "Onion", "Nashik", "APMC Nasik")


@respx.mock
async def test_timeout_raises_upstream_timeout() -> None:
    respx.get(RESOURCE_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))

    with pytest.raises(UpstreamTimeoutError):
        await get_latest_prices("Maharashtra", "Onion")


@respx.mock
async def test_server_error_raises_data_unavailable_without_leaking_the_key() -> None:
    respx.get(RESOURCE_URL).mock(return_value=httpx.Response(502))

    with pytest.raises(DataUnavailableError) as excinfo:
        await get_latest_prices("Maharashtra", "Onion")

    assert "502" in str(excinfo.value)
    assert FAKE_KEY not in str(excinfo.value)


@respx.mock
async def test_unreadable_records_raise_schema_mismatch() -> None:
    broken = {"records": [{"unexpected": "shape"}]}
    respx.get(RESOURCE_URL).mock(return_value=httpx.Response(200, json=broken))

    with pytest.raises(SchemaMismatchError):
        await get_latest_prices("Maharashtra", "Onion")


async def test_missing_api_key_raises_data_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_GOV_IN_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(DataUnavailableError):
        await get_latest_prices("Maharashtra", "Onion")


@respx.mock
async def test_text_prices_in_older_records_are_parsed_too() -> None:
    payload = load_payload()
    expected = payload["records"][0]["Modal_Price"]
    for record in payload["records"]:
        for name in ("Min_Price", "Max_Price", "Modal_Price"):
            record[name] = str(record[name])
    respx.get(RESOURCE_URL).mock(return_value=httpx.Response(200, json=payload))

    result = await get_latest_prices("Maharashtra", "Onion", "Nashik")

    assert result.value.prices[0].modal_price == float(expected)
