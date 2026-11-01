import httpx
import structlog
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from advisor.errors import DataUnavailableError, SchemaMismatchError, UpstreamTimeoutError
from advisor.models import Provenanced

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
SOURCE = "Open-Meteo Geocoding API"

log = structlog.get_logger()


class Place(BaseModel):
    name: str
    latitude: float
    longitude: float
    timezone: str | None = None
    country: str | None = None
    admin1: str | None = None  # state
    admin2: str | None = None  # district


class _GeocodeResponse(BaseModel):
    results: list[Place] = []


@retry(
    retry=retry_if_exception_type(UpstreamTimeoutError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
)
async def geocode(query: str) -> Provenanced[Place]:
    """Look up a place name and return its real coordinates with provenance."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                GEOCODING_URL,
                params={"name": query, "count": 1, "language": "en", "format": "json"},
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise UpstreamTimeoutError("Geocoding request timed out") from exc
    except httpx.HTTPError as exc:
        raise DataUnavailableError(f"Geocoding service error: {exc}") from exc

    try:
        parsed = _GeocodeResponse.model_validate(response.json())
    except ValueError as exc:  # invalid JSON or failed validation
        raise SchemaMismatchError("Unexpected geocoding response shape") from exc

    if not parsed.results:
        raise DataUnavailableError(f"No place found for '{query}'")

    place = parsed.results[0]
    log.info("geocoded", query=query, place=place.name)
    return Provenanced[Place](value=place, source=SOURCE)
