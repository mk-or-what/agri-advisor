import json
from pathlib import Path

import httpx
import pytest
import respx

from advisor.clients.geocode import GEOCODING_URL, geocode
from advisor.errors import DataUnavailableError, SchemaMismatchError, UpstreamTimeoutError

FIXTURES = Path(__file__).parent.parent / "fixtures"


@respx.mock
async def test_geocode_parses_real_response() -> None:
    payload = json.loads((FIXTURES / "geocode_nashik.json").read_text())
    respx.get(GEOCODING_URL).mock(return_value=httpx.Response(200, json=payload))

    result = await geocode("Nashik")

    assert result.value.name == "Nashik"
    assert result.value.latitude == pytest.approx(19.99727)
    assert result.source == "Open-Meteo Geocoding API"


@respx.mock
async def test_geocode_unknown_place_raises_data_unavailable() -> None:
    no_results = {"generationtime_ms": 0.1}
    respx.get(GEOCODING_URL).mock(return_value=httpx.Response(200, json=no_results))

    with pytest.raises(DataUnavailableError):
        await geocode("zzzz-not-a-place")


@respx.mock
async def test_geocode_timeout_raises_upstream_timeout() -> None:
    respx.get(GEOCODING_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))

    with pytest.raises(UpstreamTimeoutError):
        await geocode("Nashik")


@respx.mock
async def test_geocode_wrong_shape_raises_schema_mismatch() -> None:
    broken = {"results": [{"name": "Nashik"}]}
    respx.get(GEOCODING_URL).mock(return_value=httpx.Response(200, json=broken))

    with pytest.raises(SchemaMismatchError):
        await geocode("Nashik")
