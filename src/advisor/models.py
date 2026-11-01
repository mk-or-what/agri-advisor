from datetime import UTC, datetime

from pydantic import BaseModel, Field


class Provenanced[T](BaseModel):
    """An external value together with where it came from and when it was fetched."""

    value: T
    unit: str | None = None
    source: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
