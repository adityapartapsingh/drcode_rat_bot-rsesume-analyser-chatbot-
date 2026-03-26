"""
main.py
Entry point for the Resume Analyzer Bot.
Runs:
  - Telegram bot (polling, in main thread)
  - Flask server (WhatsApp webhook, in background thread)
"""
import os
import threading
import logging

from dotenv import load_dotenv  # type: ignore

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)


def run_flask():
    """Start the Flask server for WhatsApp webhook."""
    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN", "")

    if not twilio_sid or twilio_sid == "your_twilio_account_sid":
        logger.warning(
            "Twilio credentials not configured – WhatsApp bot will NOT start. "
            "Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in .env to enable it."
        )
        return

    from src.whatsapp_bot import app as flask_app  # type: ignore
    port = int(os.getenv("FLASK_PORT", 5000))
    logger.info(f"Starting WhatsApp webhook server on port {port}...")
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)


def run_telegram():
    """Start the Telegram bot (blocking)."""
    from src.telegram_bot import create_telegram_app  # type: ignore
    telegram_app = create_telegram_app()
    logger.info("Starting Telegram bot (polling)...")
    telegram_app.run_polling(allowed_updates=["message"], drop_pending_updates=True)


if __name__ == "__main__":
    # Start Flask in a background thread (only if Twilio is configured)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Run Telegram bot in the main thread
    run_telegram()
