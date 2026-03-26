"""
telegram_bot.py
Handles all Telegram bot interactions using python-telegram-bot v21.
"""
import os
import logging
import tempfile

from telegram import Update  # type: ignore
from telegram.ext import (  # type: ignore
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode  # type: ignore

from src import session_store as ss  # type: ignore
from src.analyzer import analyze_resume  # type: ignore
from src.file_handler import extract_text  # type: ignore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


# ─── Command Handlers ─────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_key = str(update.effective_user.id)
    ss.reset_session(user_key)
    ss.set_state(user_key, ss.AWAITING_JD)

    await update.message.reply_text(
        "👋 *Welcome to the Resume Analyzer Bot!*\n\n"
        "I'll help you evaluate your resume against a job description and give you a score out of 10 "
        "along with personalized improvement suggestions.\n\n"
        "📋 *Step 1:* Please paste the *Job Description* below.\n\n"
        "_Tip: Copy-paste the full JD text for best results._",
        parse_mode=ParseMode.MARKDOWN,
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_key = str(update.effective_user.id)
    ss.reset_session(user_key)
    ss.set_state(user_key, ss.AWAITING_JD)

    await update.message.reply_text(
        "🔄 *Session reset!*\n\n"
        "Ready for a fresh analysis. Please paste the *Job Description* to begin.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Resume Analyzer Bot – Help*\n\n"
        "/start – Start a new analysis session\n"
        "/reset – Clear current session and start over\n"
        "/help  – Show this help message\n\n"
        "*How it works:*\n"
        "1️⃣ Send me the Job Description (text)\n"
        "2️⃣ Send me your Resume (PDF, DOCX, or text)\n"
        "3️⃣ I'll score your resume and give you suggestions!\n",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── Message Handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_key = str(update.effective_user.id)
    session = ss.get_session(user_key)
    state = session["state"]
    text = update.message.text or ""

    if state == ss.IDLE:
        await update.message.reply_text(
            "👋 Send /start to begin your resume analysis!",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif state == ss.AWAITING_JD:
        if len(text.strip()) < 50:
            await update.message.reply_text(
                "⚠️ That seems too short for a job description. Please paste the full JD text.",
            )
            return
        ss.set_jd(user_key, text.strip())
        ss.set_state(user_key, ss.AWAITING_RESUME)
        await update.message.reply_text(
            "✅ *Job Description saved!*\n\n"
            "📄 *Step 2:* Now send me your *Resume*.\n\n"
            "You can either:\n"
            "• Upload a *PDF* or *DOCX* file 📎\n"
            "• Paste your resume text directly 📝",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif state == ss.AWAITING_RESUME:
        # User pasted resume text
        if len(text.strip()) < 100:
            await update.message.reply_text(
                "⚠️ That seems too short for a resume. Please paste more content or upload a file.",
            )
            return
        ss.set_resume(user_key, text.strip())
        await _run_analysis(update, user_key, session)

    elif state == ss.ANALYZING:
        await update.message.reply_text("⏳ Analysis in progress, please wait...")

    elif state == ss.DONE:
        await update.message.reply_text(
            "✅ Analysis complete! Send /reset to analyze another resume.",
        )


# ─── Document Handler ─────────────────────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_key = str(update.effective_user.id)
    session = ss.get_session(user_key)
    state = session["state"]

    if state != ss.AWAITING_RESUME:
        await update.message.reply_text(
            "⚠️ Please start with /start and paste the Job Description first before sending your resume.",
        )
        return

    doc = update.message.document
    file_name = doc.file_name or "resume.pdf"
    ext = os.path.splitext(file_name)[1].lower()

    if ext not in (".pdf", ".docx", ".doc", ".txt"):
        await update.message.reply_text(
            "❌ Unsupported file type. Please upload a *PDF*, *DOCX*, or *TXT* file.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("⏳ Downloading your resume...")

    # Download the file
    tg_file = await context.bot.get_file(doc.file_id)
    save_path = os.path.join(DOWNLOADS_DIR, f"{user_key}_{file_name}")
    await tg_file.download_to_drive(save_path)

    try:
        resume_text = extract_text(save_path)
    except ValueError as e:
        await update.message.reply_text(f"❌ Error reading file: {e}")
        return
    finally:
        # Clean up downloaded file
        if os.path.exists(save_path):
            os.remove(save_path)

    if len(resume_text.strip()) < 50:
        await update.message.reply_text(
            "⚠️ The file seems empty or unreadable. Please try a different file or paste the text."
        )
        return

    ss.set_resume(user_key, resume_text)
    await _run_analysis(update, user_key, session)


# ─── Core Analysis Runner ─────────────────────────────────────────────────────

async def _run_analysis(update: Update, user_key: str, session: dict):
    ss.set_state(user_key, ss.ANALYZING)
    await update.message.reply_text(
        "🔍 *Analyzing your resume against the job description...*\n\n"
        "_This may take 10-20 seconds._",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        result = analyze_resume(session["jd"], session["resume"])
        ss.set_state(user_key, ss.DONE)
        await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        ss.set_state(user_key, ss.AWAITING_RESUME)
        logger.error(f"Analysis failed for {user_key}: {e}")
        await update.message.reply_text(
            f"❌ Analysis failed: {e}\n\nPlease try again or send /reset."
        )


# ─── Bot Setup ─────────────────────────────────────────────────────────────────

def create_telegram_app() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
