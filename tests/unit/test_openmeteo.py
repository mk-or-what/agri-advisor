import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from advisor.clients.openmeteo import FORECAST_URL, get_forecast
from advisor.errors import DataUnavailableError, SchemaMismatchError, UpstreamTimeoutError

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_payload() -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / "openmeteo_forecast_nashik.json").read_text())  # type: ignore[no-any-return]


@respx.mock
async def test_forecast_parses_real_response() -> None:
    payload = load_payload()
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=payload))

    result = await get_forecast(19.99727, 73.79096, 3)

    assert len(result.value.daily) == 3
    assert len(result.value.soil_moisture) == 72
    assert result.value.daily[0].day == date.fromisoformat(payload["daily"]["time"][0])
    assert result.value.daily[0].precipitation_mm == payload["daily"]["precipitation_sum"][0]
    assert result.source == "Open-Meteo Forecast API"


@respx.mock
async def test_forecast_changed_unit_raises_schema_mismatch() -> None:
    payload = load_payload()
    payload["daily_units"]["precipitation_sum"] = "inch"
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=payload))

    with pytest.raises(SchemaMismatchError):
        await get_forecast(19.99727, 73.79096, 3)


@respx.mock
async def test_forecast_timeout_raises_upstream_timeout() -> None:
    respx.get(FORECAST_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))

    with pytest.raises(UpstreamTimeoutError):
        await get_forecast(19.99727, 73.79096, 3)


@respx.mock
async def test_forecast_server_error_raises_data_unavailable() -> None:
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(DataUnavailableError):
        await get_forecast(19.99727, 73.79096, 3)


async def test_forecast_rejects_invalid_days() -> None:
    with pytest.raises(ValueError):
        await get_forecast(19.99727, 73.79096, 0)
