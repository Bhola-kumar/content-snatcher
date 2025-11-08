# app/main.py
import json
import logging
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from pydantic import BaseModel
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from app.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

app = FastAPI(title="Telegram Webhook + FastAPI")
settings = get_settings()

# --- Core processing logic
def process_text(text: str) -> str:
    return f"bhola {text}"

# --- Pydantic models
class In(BaseModel):
    text: str

class Out(BaseModel):
    result: str

# --- Telegram Application (v22+)
tg_app: Application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! Send me any text and I'll add 'bhola' before it.")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    result = process_text(user_text)
    await update.message.reply_text(result)

tg_app.add_handler(CommandHandler("start", cmd_start))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

# --- Lifecycle hooks
@app.on_event("startup")
async def on_startup():
    # 1) Initialize telegram app (required in v22+ before process_update)
    await tg_app.initialize()

    # 2) If we have a public URL, set webhook automatically
    if settings.PUBLIC_BASE_URL:
        webhook_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/telegram/webhook"
        payload = {"url": webhook_url, "secret_token": settings.WEBHOOK_SECRET_TOKEN}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook",
                json=payload,
            )
        logger.info("setWebhook -> %s", r.json())

@app.on_event("shutdown")
async def on_shutdown():
    # Clean shutdown to release resources
    try:
        await tg_app.shutdown()
        await tg_app.stop()  # harmless if not started
    except Exception as e:
        logger.warning("Shutdown warning: %s", e)

# --- FastAPI routes
@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.get("/")
async def root():
    return {"ok": True, "hint": "POST JSON to /process or send a Telegram message to the bot"}

@app.post("/process", response_model=Out)
async def process_endpoint(inp: In):
    return Out(result=process_text(inp.text))

# --- Telegram webhook endpoint
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    # Verify Telegram secret
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid secret token")

    body = await request.body()
    try:
        update = Update.de_json(json.loads(body), tg_app.bot)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid update payload")

    # Process update (tg_app must be initialized; handled in startup)
    await tg_app.process_update(update)
    return Response(status_code=200)
