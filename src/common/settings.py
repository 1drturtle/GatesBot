from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    prefix: str
    dev_id: int
    token: str | None
    mongo_url: str | None
    mongo_db: str
    environment: str


def load_settings() -> Settings:
    return Settings(
        prefix=os.getenv("DISCORD_BOT_PREFIX", "="),
        dev_id=int(os.getenv("DEV_ID", "175386962364989440")),
        token=os.getenv("DISCORD_BOT_TOKEN"),
        mongo_url=os.getenv("DISCORD_MONGO_URL"),
        mongo_db=os.getenv("MONGO_DB", "testgatesdb"),
        environment=os.getenv("ENVIRONMENT", "testing"),
    )


settings = load_settings()
