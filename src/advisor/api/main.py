import structlog
from fastapi import FastAPI

from advisor.config import get_settings
from advisor.logging_setup import configure_logging

settings = get_settings()
configure_logging(settings.app_env)
log = structlog.get_logger()

app = FastAPI(title="Agri Advisor API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    log.info("health_check")
    return {"status": "ok", "env": settings.app_env}
