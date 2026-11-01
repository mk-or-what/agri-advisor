from datetime import date, datetime

import httpx
import structlog
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from advisor.errors import DataUnavailableError, SchemaMismatchError, UpstreamTimeoutError
from advisor.models import Provenanced

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SOURCE = "Open-Meteo Forecast API"
SOIL_VARIABLE = "soil_moisture_3_to_9cm"
EXPECTED_SOIL_UNIT = "m³/m³"
EXPECTED_DAILY_UNITS = {
    "precipitation_sum": "mm",
    "temperature_2m_max": "°C",
    "temperature_2m_min": "°C",
    "et0_fao_evapotranspiration": "mm",
}

log = structlog.get_logger()


class DailyForecast(BaseModel):
    day: date
    precipitation_mm: float | None
    temp_max_c: float | None
    temp_min_c: float | None
    et0_mm: float | None


class SoilMoistureReading(BaseModel):
    time: datetime  # local time at the location
    value_m3_m3: float | None


class Forecast(BaseModel):
    latitude: float
    longitude: float
    timezone: str
    daily: list[DailyForecast]
    soil_moisture: list[SoilMoistureReading]


class _Daily(BaseModel):
    time: list[date]
    precipitation_sum: list[float | None]
    temperature_2m_max: list[float | None]
    temperature_2m_min: list[float | None]
    et0_fao_evapotranspiration: list[float | None]


class _Hourly(BaseModel):
    time: list[datetime]
    soil_moisture_3_to_9cm: list[float | None]


class _ForecastResponse(BaseModel):
    latitude: float
    longitude: float
    timezone: str
    daily_units: dict[str, str]
    daily: _Daily
    hourly_units: dict[str, str]
    hourly: _Hourly


def _to_forecast(raw: _ForecastResponse) -> Forecast:
    for name, unit in EXPECTED_DAILY_UNITS.items():
        if raw.daily_units.get(name) != unit:
            raise SchemaMismatchError(f"Unexpected unit for {name}")
    if raw.hourly_units.get(SOIL_VARIABLE) != EXPECTED_SOIL_UNIT:
        raise SchemaMismatchError(f"Unexpected unit for {SOIL_VARIABLE}")

    d = raw.daily
    daily = [
        DailyForecast(
            day=day,
            precipitation_mm=rain,
            temp_max_c=tmax,
            temp_min_c=tmin,
            et0_mm=et0,
        )
        for day, rain, tmax, tmin, et0 in zip(
            d.time,
            d.precipitation_sum,
            d.temperature_2m_max,
            d.temperature_2m_min,
            d.et0_fao_evapotranspiration,
            strict=True,
        )
    ]
    h = raw.hourly
    soil = [
        SoilMoistureReading(time=t, value_m3_m3=v)
        for t, v in zip(h.time, h.soil_moisture_3_to_9cm, strict=True)
    ]
    return Forecast(
        latitude=raw.latitude,
        longitude=raw.longitude,
        timezone=raw.timezone,
        daily=daily,
        soil_moisture=soil,
    )


@retry(
    retry=retry_if_exception_type(UpstreamTimeoutError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    reraise=True,
)
async def get_forecast(latitude: float, longitude: float, days: int = 7) -> Provenanced[Forecast]:
    """Fetch a real forecast: rain, temperature, evapotranspiration and soil moisture."""
    if not 1 <= days <= 16:
        raise ValueError("days must be between 1 and 16")

    params: dict[str, str | float | int] = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join(EXPECTED_DAILY_UNITS),
        "hourly": SOIL_VARIABLE,
        "forecast_days": days,
        "timezone": "auto",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(FORECAST_URL, params=params)
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise UpstreamTimeoutError("Forecast request timed out") from exc
    except httpx.HTTPError as exc:
        raise DataUnavailableError(f"Forecast service error: {exc}") from exc

    try:
        forecast = _to_forecast(_ForecastResponse.model_validate(response.json()))
    except ValueError as exc:  # invalid JSON, failed validation or mismatched list lengths
        raise SchemaMismatchError("Unexpected forecast response shape") from exc

    log.info("forecast_fetched", latitude=latitude, longitude=longitude, days=days)
    return Provenanced[Forecast](value=forecast, source=SOURCE)
