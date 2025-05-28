import os
import re
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import yt_dlp
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# Retrieve Telegram bot token from environment variable
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Supported platforms (regex patterns for URL matching)
PLATFORMS = {
    "tiktok": r"https?://(www\.)?tiktok\.com/@[^/]+/video/\d+",
    "instagram": r"https?://(www\.)?instagram\.com/(p|reel)/[^/]+/",
    "twitter": r"https?://(www\.)?(twitter\.com|x\.com)/[^/]+/status/\d+",
    "tumblr": r"https?://[^/]+\.tumblr\.com/post/\d+",
}

# yt-dlp options with user-agent headers
YDL_OPTS = {
    "outtmpl": "downloads/%(id)s.%(ext)s",
    "format": "best[filesize<50M]",  # Limit to 50MB for Telegram
    "quiet": False,
    "no_warnings": False,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    },
}

# Simple HTTP server to keep Railway alive (optional for polling mode)
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_server():
    server = HTTPServer(("0.0.0.0", 8080), KeepAliveHandler)
    server.serve_forever()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("Received /start command")
    await update.message.reply_text(
        "Hi! Send me a TikTok, Instagram, Twitter/X, or Tumblr link, and I'll convert it into an attachment."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_text = update.message.text
    logger.debug(f"Received message: {message_text}")
    if not message_text:
        return
    for platform, pattern in PLATFORMS.items():
        urls = re.findall(pattern, message_text, re.IGNORECASE)
        for url in urls:
            logger.debug(f"Processing URL: {url} from {platform}")
            await process_url(update, context, url, platform)

async def process_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, platform: str) -> None:
    status_message = None
    file_path = None
    try:
        logger.debug(f"Starting processing for {url}")
        status_message = await update.message.reply_text(f"Processing media from {platform.capitalize()}...")
        os.makedirs("downloads", exist_ok=True)
        logger.debug("Creating downloads directory")

        logger.debug(f"Downloading media from {url}")
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            logger.debug(f"Downloaded file: {file_path}")

        if file_path.endswith((".mp4", ".mkv", ".webm")):
            logger.debug(f"Sending video: {file_path}")
            await context.bot.edit_message_text(
                chat_id=status_message.chat_id,
                message_id=status_message.message_id,
                text=f"Sending video from {platform.capitalize()}..."
            )
            with open(file_path, "rb") as video:
                await update.message.reply_video(video=video, caption=f"From {platform.capitalize()}: {url}")
            logger.debug("Video sent successfully")
            await context.bot.edit_message_text(
                chat_id=status_message.chat_id,
                message_id=status_message.message_id,
                text="Video sent successfully!"
            )
        elif file_path.endswith((".jpg", ".jpeg", ".png", ".gif")):
            logger.debug(f"Sending photo: {file_path}")
            await context.bot.edit_message_text(
                chat_id=status_message.chat_id,
                message_id=status_message.message_id,
                text=f"Sending photo from {platform.capitalize()}..."
            )
            with open(file_path, "rb") as photo:
                await update.message.reply_photo(photo=photo, caption=f"From {platform.capitalize()}: {url}")
            logger.debug("Photo sent successfully")
            await context.bot.edit_message_text(
                chat_id=status_message.chat_id,
                message_id=status_message.message_id,
                text="Photo sent successfully!"
            )
        else:
            logger.debug(f"Unsupported media type: {file_path}")
            await context.bot.edit_message_text(
                chat_id=status_message.chat_id,
                message_id=status_message.message_id,
                text=f"Sorry, unsupported media type from {platform}."
            )

    except Exception as e:
        logger.error(f"Error processing {url}: {str(e)}", exc_info=True)
        error_message = f"Error sending {'video' if file_path and file_path.endswith(('.mp4', '.mkv', '.webm')) else 'media'} from {platform.capitalize()}. Please try again or use a different link."
        if status_message:
            try:
                await context.bot.edit_message_text(
                    chat_id=status_message.chat_id,
                    message_id=status_message.message_id,
                    text=error_message
                )
            except Exception as edit_error:
                logger.error(f"Failed to edit message: {str(edit_error)}")
                await update.message.reply_text(error_message)
        else:
            await update.message.reply_text(error_message)

    finally:
        if file_path and os.path.exists(file_path):
            logger.debug(f"Cleaning up file: {file_path}")
            os.remove(file_path)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}", exc_info=True)
    if update and update.message:
        await update.message.reply_text("An error occurred. Please try again later.")

def main() -> None:
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        return
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    logger.debug("Starting bot polling")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    main()
