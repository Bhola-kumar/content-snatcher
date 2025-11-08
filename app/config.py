# app/config.py
import os
import logging
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("app.config")

class Settings(BaseModel):
    TELEGRAM_BOT_TOKEN: str
    WEBHOOK_SECRET_TOKEN: str
    PUBLIC_BASE_URL: str | None = None

def get_settings() -> Settings:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    secret = os.environ.get("WEBHOOK_SECRET_TOKEN")
    # Prefer explicit PUBLIC_BASE_URL; otherwise use Render’s RENDER_EXTERNAL_URL
    public = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL")

    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    if not secret:
        raise RuntimeError("WEBHOOK_SECRET_TOKEN not set")

    s = Settings(
        TELEGRAM_BOT_TOKEN=token,
        WEBHOOK_SECRET_TOKEN=secret,
        PUBLIC_BASE_URL=public,
    )
    logger.info("Settings loaded. PUBLIC_BASE_URL=%s", s.PUBLIC_BASE_URL)
    return s
