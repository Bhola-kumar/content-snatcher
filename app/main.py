import json
import logging
import os
import re
import tempfile

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

# Video download/upload imports
import yt_dlp
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

# App & settings
app = FastAPI(title="Telegram Webhook + FastAPI")
settings = get_settings()

# ---------------------- Core Text Logic ----------------------
def process_text(text: str) -> str:
    return f"bhola {text}"

class In(BaseModel):
    text: str

class Out(BaseModel):
    result: str

# ---------------------- YouTube Helpers ----------------------
def download_video(url: str) -> str:
    """Downloads a video and returns local file path."""
    tmpdir = tempfile.mkdtemp(prefix="yt_simple_")
    outtmpl = os.path.join(tmpdir, "%(title)s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "best",
        "noplaylist": True,
        "quiet": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    return filename


def build_youtube_client():
    creds = Credentials(
        token=None,
        refresh_token=os.getenv("YT_REFRESH_TOKEN"),
        client_id=os.getenv("YT_CLIENT_ID"),
        client_secret=os.getenv("YT_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_to_youtube(video_path: str) -> str:
    youtube = build_youtube_client()

    body = {
        "snippet": {"title": "Uploaded via Bot", "description": "Auto-uploaded video"},
        "status": {"privacyStatus": "private"},
    }

    media = MediaFileUpload(video_path, chunksize=1024 * 1024, resumable=True)

    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )

    response = None
    while response is None:
        _, response = request.next_chunk()

    return response.get("id")

# ---------------------- Telegram App ----------------------
tg_app: Application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! Send me text or a URL.")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()

    # Check for URLs
    url_match = re.search(r"(https?://\S+)", text)
    if url_match:
        url = url_match.group(1)
        await msg.reply_text("✅ URL detected. Downloading video...")

        try:
            path = download_video(url)
            vid = upload_to_youtube(path)
            link = f"https://youtu.be/{vid}"

            await msg.reply_text(f"✅ Uploaded successfully!\n{link}")
        except Exception as e:
            await msg.reply_text(f"❌ Error: {str(e)}")

        return

    # Otherwise simple text processing
    result = process_text(text)
    await msg.reply_text(result)

tg_app.add_handler(CommandHandler("start", cmd_start))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

# ---------------------- Lifecycle ----------------------
@app.on_event("startup")
async def on_startup():
    await tg_app.initialize()

    if settings.PUBLIC_BASE_URL:
        webhook = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/telegram/webhook"
        payload = {"url": webhook, "secret_token": settings.WEBHOOK_SECRET_TOKEN}

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook",
                json=payload,
            )
            logger.info("Webhook set -> %s", r.json())

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await tg_app.shutdown()
        await tg_app.stop()
    except:
        pass

# ---------------------- Routes ----------------------
@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.post("/process", response_model=Out)
async def process_endpoint(inp: In):
    return Out(result=process_text(inp.text))

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid secret")

    body = await request.body()
    update = Update.de_json(json.loads(body), tg_app.bot)

    await tg_app.process_update(update)
    return Response(status_code=200)
