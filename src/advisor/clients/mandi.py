from datetime import date, datetime
from typing import Literal

import httpx
import structlog
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from advisor.config import get_settings
from advisor.errors import DataUnavailableError, SchemaMismatchError, UpstreamTimeoutError
from advisor.models import Provenanced

RESOURCE_URL = "https://api.data.gov.in/resource/35985678-0d79-46b4-9ed6-6f13308a1d24"
SOURCE = "Agmarknet via data.gov.in (Variety-wise Daily Market Prices)"
# The server stalls requests that use httpx's default User-Agent, so we identify ourselves.
USER_AGENT = "agri-advisor/0.1 (student hackathon project)"

log = structlog.get_logger()

Scope = Literal["market", "district", "state"]


class MandiPrice(BaseModel):
    arrival_date: date
    state: str
    district: str
    market: str
    commodity: str
    variety: str
    grade: str
    min_price: float  # Rs per quintal
    max_price: float  # Rs per quintal
    modal_price: float  # Rs per quintal


class MandiPrices(BaseModel):
    scope: Scope  # how local the prices are: market, district or whole state
    prices: list[MandiPrice]


class _RawRecord(BaseModel):
    Arrival_Date: str
    State: str
    District: str
    Market: str
    Commodity: str
    Variety: str
    Grade: str
    Min_Price: str | int | float
    Max_Price: str | int | float
    Modal_Price: str | int | float


class _Response(BaseModel):
    records: list[dict[str, object]] = []


def _to_price(raw: _RawRecord) -> MandiPrice:
    return MandiPrice(
        arrival_date=datetime.strptime(raw.Arrival_Date.strip(), "%d/%m/%Y").date(),
        state=raw.State.strip(),
        district=raw.District.strip(),
        market=raw.Market.strip(),
        commodity=raw.Commodity.strip(),
        variety=raw.Variety.strip(),
        grade=raw.Grade.strip(),
        min_price=float(raw.Min_Price),
        max_price=float(raw.Max_Price),
        modal_price=float(raw.Modal_Price),
    )


@retry(
    retry=retry_if_exception_type(UpstreamTimeoutError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, max=8),
    reraise=True,
)
async def _fetch(filters: dict[str, str], limit: int) -> list[MandiPrice]:
    api_key = get_settings().data_gov_in_api_key
    if not api_key:
        raise DataUnavailableError("DATA_GOV_IN_API_KEY is not configured")

    params: dict[str, str | int] = {
        "api-key": api_key,
        "format": "json",
        "limit": limit,
        "sort[Arrival_Date]": "desc",
    }
    for name, value in filters.items():
        params[f"filters[{name}]"] = value

    # Error messages are written by hand on purpose: httpx's own messages contain the
    # full URL, which contains the API key. "from None" also hides the original error.
    try:
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(RESOURCE_URL, params=params)
            response.raise_for_status()
    except httpx.TimeoutException:
        raise UpstreamTimeoutError("Mandi price request timed out") from None
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise DataUnavailableError(f"Mandi price service returned HTTP {status}") from None
    except httpx.HTTPError:
        raise DataUnavailableError("Mandi price service could not be reached") from None

    try:
        body = _Response.model_validate(response.json())
    except ValueError:
        raise SchemaMismatchError("Unexpected mandi response shape") from None

    prices: list[MandiPrice] = []
    skipped = 0
    for record in body.records:
        try:
            prices.append(_to_price(_RawRecord.model_validate(record)))
        except ValueError:
            skipped += 1
    if skipped:
        log.warning("mandi_records_skipped", skipped=skipped, kept=len(prices))
    if body.records and not prices:
        raise SchemaMismatchError("No mandi record could be read")
    return prices


# The server cannot match market names reliably (its data has stray spaces), so we
# fetch a district's newest records and pick the market out ourselves.
DISTRICT_SCAN_LIMIT = 100


def _result(scope: Scope, prices: list[MandiPrice]) -> Provenanced[MandiPrices]:
    log.info("mandi_prices_fetched", scope=scope, count=len(prices))
    return Provenanced[MandiPrices](
        value=MandiPrices(scope=scope, prices=prices),
        unit="INR per quintal",
        source=SOURCE,
    )


async def get_latest_prices(
    state: str,
    commodity: str,
    district: str | None = None,
    market: str | None = None,
    limit: int = 20,
) -> Provenanced[MandiPrices]:
    """Newest real mandi prices, widening from market to district to state if needed."""
    base = {"State": state, "Commodity": commodity}

    if district and market:
        wanted = market.strip().casefold()
        records = await _fetch({**base, "District": district}, DISTRICT_SCAN_LIMIT)
        in_market = [p for p in records if p.market.casefold() == wanted][:limit]
        if in_market:
            return _result("market", in_market)
        log.info("mandi_scope_empty", scope="market")
        if records:
            return _result("district", records[:limit])
        log.info("mandi_scope_empty", scope="district")
    elif district:
        records = await _fetch({**base, "District": district}, limit)
        if records:
            return _result("district", records)
        log.info("mandi_scope_empty", scope="district")

    records = await _fetch(base, limit)
    if records:
        return _result("state", records)
    raise DataUnavailableError(f"No mandi prices found for {commodity} in {state}")
