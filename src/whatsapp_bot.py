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
from src.analyzer import analyze_resume, ask_followup  # type: ignore
from src.file_handler import extract_text  # type: ignore

logger = logging.getLogger(__name__)

app = Flask(__name__)

DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


def _send_whatsapp(to: str, body: str):
    """Send a WhatsApp message via Twilio REST API (for async / long messages)."""
    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    from_num = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
    
    # Twilio limit is 1600 characters, but Unicode/emojis count as more bytes.
    # 800 safely avoids hitting any encoded string limits.
    max_length = 800  
    
    if len(body) <= max_length:
        client.messages.create(from_=from_num, to=to, body=str(body))
        return

    # Split into chunks cleanly by newline
    lines = body.split('\n')
    current_chunk = ""
    
    for line in lines:
        # If a single line is insanely long, force split it (edge case)
        if len(line) > max_length:
            if current_chunk:
                client.messages.create(from_=from_num, to=to, body=str(current_chunk).strip())
                current_chunk = ""
            for i in range(0, len(line), max_length):
                client.messages.create(from_=from_num, to=to, body=str(line)[i:i+max_length])  # type: ignore
            continue
            
        if len(current_chunk) + len(line) + 1 > max_length:
            if current_chunk:
                client.messages.create(from_=from_num, to=to, body=str(current_chunk).strip())
            current_chunk = line + "\n"
        else:
            current_chunk = str(current_chunk) + line + "\n"
            
    if str(current_chunk).strip():
        client.messages.create(from_=from_num, to=to, body=str(current_chunk).strip())


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
            "📋 Step 1: Please send me the Job Description (paste text OR upload a PDF/DOCX file)."
        )
        return str(resp)

    # ── AWAITING_JD or AWAITING_RESUME ─────────────────────────────────────────
    if state in (ss.AWAITING_JD, ss.AWAITING_RESUME):
        extracted_text = None
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

            resp.message("⏳ Downloading document, please wait...")
            try:
                save_path = _download_twilio_media(media_url, ext)
                extracted_text = extract_text(save_path)
            except Exception as e:
                resp.message(f"❌ Error reading file: {e}")
                return str(resp)
            finally:
                if save_path and os.path.exists(save_path):
                    os.remove(save_path)

        # Text paste
        elif body and len(body) >= 50:
            extracted_text = body

        else:
            msg_type = "Job Description" if state == ss.AWAITING_JD else "resume"
            resp.message(
                f"⚠️ That seems too short for a {msg_type}.\n\n"
                "Please paste more text OR upload a PDF/DOCX file."
            )
            return str(resp)

        if not extracted_text or len(extracted_text) < 50:
            resp.message("⚠️ The file or text is too short or empty. Please try again.")
            return str(resp)

        if state == ss.AWAITING_JD:
            ss.set_jd(user_key, extracted_text)
            ss.set_state(user_key, ss.AWAITING_RESUME)
            resp.message(
                "✅ Job Description saved!\n\n"
                "📄 Step 2: Now send your Resume.\n\n"
                "You can:\n"
                "• Upload a PDF or DOCX file\n"
                "• Paste your resume text directly"
            )
            return str(resp)

        else:  # state == ss.AWAITING_RESUME
            ss.set_resume(user_key, extracted_text)
            ss.set_state(user_key, ss.ANALYZING)

            # Acknowledge synchronously; analysis happens and is sent via REST
            resp.message("🔍 Analyzing your resume... I'll reply shortly (10-20 seconds).")

            # Run analysis and send result (outside TwiML response, via REST API)
            try:
                result = _plain_text_analysis(session["jd"], extracted_text)
                ss.set_state(user_key, ss.DONE)
                _send_whatsapp(from_number, result)
                _send_whatsapp(from_number, "💬 You can now ask follow-up questions, or send 'Reset' to start over.")
            except Exception as e:
                logger.error(f"WhatsApp analysis failed: {e}")
                ss.set_state(user_key, ss.AWAITING_RESUME)
                _send_whatsapp(from_number, f"❌ Analysis failed: {e}\n\nPlease try again.")

            return str(resp)

    if state == ss.ANALYZING:
        resp.message("⏳ Still analyzing, please wait...")
        return str(resp)

    if state == ss.DONE:
        if not body:
            return str(resp)
        resp.message("⏳ Thinking... I'll reply in a moment.")
        try:
            answer = ask_followup(session.get("jd", ""), session.get("resume", ""), body)
            answer = answer.replace("*", "").replace("_", "").replace("`", "")
            _send_whatsapp(from_number, answer)
        except Exception as e:
            logger.error(f"WhatsApp follow-up failed: {e}")
            _send_whatsapp(from_number, f"❌ Failed to answer: {e}")
        return str(resp)

    resp.message("Something went wrong. Send 'Reset' to start over.")
    return str(resp)
