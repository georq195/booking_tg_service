from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    admin_ids: Annotated[list[int], NoDecode] = []
    timezone: str = "Europe/Moscow"
    slot_step_min: int = 30
    cancel_deadline_hours: int = 2
    database_url: str = "sqlite+aiosqlite:///./data/bookings.db"
    gsheets_credentials_path: str | None = None
    gsheets_spreadsheet_id: str | None = None

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v):
        if isinstance(v, str):
            return [int(p) for p in v.split(",") if p.strip()]
        return v

    @field_validator("gsheets_credentials_path", "gsheets_spreadsheet_id", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return v or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
