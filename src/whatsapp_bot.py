"""
whatsapp_bot.py
Flask webhook to handle Twilio WhatsApp messages.
Uses the same session store and analyzer as the Telegram bot.
"""
import os
import logging
import tempfile

import requests  # type: ignore
from flask import Flask, request  # type: ignore
from twilio.twiml.messaging_response import MessagingResponse  # type: ignore
from twilio.rest import Client  # type: ignore

from src import session_store as ss  # type: ignore
from src.analyzer import analyze_resume  # type: ignore
from src.file_handler import extract_text  # type: ignore

logger = logging.getLogger(__name__)

app = Flask(__name__)

DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


def _send_whatsapp(to: str, body: str):
    """Send a WhatsApp message via Twilio REST API (for async / long messages)."""
    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    client.messages.create(
        from_=os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886"),
        to=to,
        body=body,
    )


def _plain_text_analysis(jd: str, resume: str) -> str:
    """Run analysis and strip markdown formatting for WhatsApp."""
    result = analyze_resume(jd, resume)
    # Remove markdown bold/italic markers WhatsApp doesn't render
    result = result.replace("*", "").replace("_", "").replace("`", "")
    return result


def _download_twilio_media(media_url: str, suffix: str) -> str:
    """Download a Twilio media file using Basic Auth and return local path."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    save_path = os.path.join(DOWNLOADS_DIR, f"wa_resume{suffix}")
    response = requests.get(media_url, auth=(account_sid, auth_token), timeout=30)
    response.raise_for_status()
    with open(save_path, "wb") as f:
        f.write(response.content)
    return save_path


@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    from_number = request.form.get("From", "")  # e.g. whatsapp:+919876543210
    body = request.form.get("Body", "").strip()
    num_media = int(request.form.get("NumMedia", 0))
    media_url = request.form.get("MediaUrl0", "")
    media_content_type = request.form.get("MediaContentType0", "")

    user_key = f"wa_{from_number}"
    session = ss.get_session(user_key)
    state = session["state"]

    resp = MessagingResponse()

    # ── Handle reset / start commands ──────────────────────────────────────────
    if body.lower() in ("hi", "hello", "start", "/start", "reset", "/reset"):
        ss.reset_session(user_key)
        ss.set_state(user_key, ss.AWAITING_JD)
        resp.message(
            "👋 Welcome to the Resume Analyzer Bot!\n\n"
            "I'll score your resume against a job description (out of 10) and "
            "give you personalized improvement tips.\n\n"
            "📋 Step 1: Please send me the Job Description text."
        )
        return str(resp)

    # ── AWAITING_JD ────────────────────────────────────────────────────────────
    if state == ss.IDLE:
        resp.message("👋 Send 'Hi' or 'Start' to begin your resume analysis!")
        return str(resp)

    if state == ss.AWAITING_JD:
        if len(body) < 50:
            resp.message("⚠️ That seems too short. Please paste the full Job Description.")
            return str(resp)
        ss.set_jd(user_key, body)
        ss.set_state(user_key, ss.AWAITING_RESUME)
        resp.message(
            "✅ Job Description saved!\n\n"
            "📄 Step 2: Now send your Resume.\n\n"
            "You can:\n"
            "• Upload a PDF or DOCX file\n"
            "• Paste your resume text directly"
        )
        return str(resp)

    # ── AWAITING_RESUME ────────────────────────────────────────────────────────
    if state == ss.AWAITING_RESUME:
        if state == ss.ANALYZING:
            resp.message("⏳ Still analyzing, please wait...")
            return str(resp)

        resume_text = None
        save_path = None

        # File upload
        if num_media > 0 and media_url:
            ext = ""
            if "pdf" in media_content_type:
                ext = ".pdf"
            elif "docx" in media_content_type or "word" in media_content_type:
                ext = ".docx"
            elif "text" in media_content_type:
                ext = ".txt"
            else:
                resp.message("❌ Unsupported file type. Please send a PDF, DOCX, or TXT file.")
                return str(resp)

            resp.message("⏳ Downloading your resume, please wait...")
            try:
                save_path = _download_twilio_media(media_url, ext)
                resume_text = extract_text(save_path)
            except Exception as e:
                resp.message(f"❌ Error reading file: {e}")
                return str(resp)
            finally:
                if save_path and os.path.exists(save_path):
                    os.remove(save_path)

        # Text paste
        elif body and len(body) >= 100:
            resume_text = body

        else:
            resp.message(
                "⚠️ That seems too short for a resume.\n\n"
                "Please paste more text OR upload a PDF/DOCX file."
            )
            return str(resp)

        ss.set_resume(user_key, resume_text)
        ss.set_state(user_key, ss.ANALYZING)

        # Acknowledge synchronously; analysis happens and is sent via REST
        resp.message("🔍 Analyzing your resume... I'll reply shortly (10-20 seconds).")

        # Run analysis and send result (outside TwiML response, via REST API)
        try:
            result = _plain_text_analysis(session["jd"], resume_text)
            ss.set_state(user_key, ss.DONE)
            _send_whatsapp(from_number, result)
            _send_whatsapp(from_number, "Send 'Reset' to analyze another resume.")
        except Exception as e:
            logger.error(f"WhatsApp analysis failed: {e}")
            ss.set_state(user_key, ss.AWAITING_RESUME)
            _send_whatsapp(from_number, f"❌ Analysis failed: {e}\n\nPlease try again.")

        return str(resp)

    if state == ss.ANALYZING:
        resp.message("⏳ Still analyzing, please wait...")
        return str(resp)

    if state == ss.DONE:
        resp.message("✅ Analysis complete! Send 'Reset' to analyze another resume.")
        return str(resp)

    resp.message("Something went wrong. Send 'Reset' to start over.")
    return str(resp)
