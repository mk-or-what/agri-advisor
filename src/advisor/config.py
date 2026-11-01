from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables and the .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    llm_api_key: str = ""
    data_gov_in_api_key: str = ""
    jwt_secret: str = ""
    database_url: str = "sqlite:///./advisor.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
