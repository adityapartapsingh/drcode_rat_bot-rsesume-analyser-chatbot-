# 📄 Resume Analyzer Bot — Project Explanation

> A complete guide to explain this project in an interview setting.

---

## 🎯 What Does This Project Do?

This is a **Telegram + WhatsApp chatbot** that:
1. Asks the user to paste a **Job Description (JD)**
2. Asks the user to upload their **Resume** (PDF / DOCX / text)
3. Uses **Google Gemini AI** to analyze how well the resume matches the JD
4. Returns a **score out of 10** + **strengths, weaknesses, missing keywords, and improvement suggestions**

---

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| **Python 3.13** | Core programming language |
| **Google Gemini 2.5 Flash** | AI model for resume analysis |
| **python-telegram-bot v21** | Telegram Bot API wrapper |
| **Twilio API** | WhatsApp messaging |
| **Flask** | Web server to receive WhatsApp webhook |
| **pdfplumber** | Extract text from PDF resumes |
| **python-docx** | Extract text from DOCX resumes |
| **python-dotenv** | Load secrets from `.env` file |

---

## 📁 Project Structure

```
bot/
├── main.py                 # Entry point — starts both bots
├── .env                    # Secret keys (Gemini, Telegram, Twilio)
├── requirements.txt        # Python dependencies
├── pyrightconfig.json      # Linter configuration
└── src/
    ├── __init__.py         # Makes src a Python package
    ├── session_store.py    # Tracks each user's conversation state
    ├── file_handler.py     # Extracts text from PDF/DOCX files
    ├── analyzer.py         # AI analysis using Google Gemini
    ├── telegram_bot.py     # All Telegram bot logic
    └── whatsapp_bot.py     # WhatsApp webhook (Flask server)
```

---

## 🔍 File-by-File Explanation

---

### `main.py` — Entry Point

```python
# Starts WhatsApp Flask server in a background thread
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# Starts Telegram bot in the main thread (blocking)
run_telegram()
```

**Key concepts:**
- Uses Python `threading` to run Flask and Telegram simultaneously
- Flask runs as a **daemon thread** — it stops automatically if the main thread (Telegram) stops
- `drop_pending_updates=True` clears any stale messages from previous runs, preventing Conflict errors
- If Twilio credentials are not set in `.env`, the WhatsApp server silently skips and only Telegram runs

---

### `src/session_store.py` — Conversation State Machine

This is the **memory** of the bot. Every user (identified by their chat ID or phone number) goes through these states:

```
IDLE → AWAITING_JD → AWAITING_RESUME → ANALYZING → DONE
```

```python
IDLE = "IDLE"           # User hasn't started yet
AWAITING_JD = "AWAITING_JD"         # Waiting for job description
AWAITING_RESUME = "AWAITING_RESUME" # Waiting for resume
ANALYZING = "ANALYZING"             # AI is processing
DONE = "DONE"                       # Analysis complete
```

**Why this is important:**
- Without state tracking, the bot wouldn't know if a message is a JD or a resume
- Uses an in-memory Python `dict` — simple and fast for single-server deployments
- Each user's state is stored independently so multiple users can use the bot simultaneously

---

### `src/file_handler.py` — Resume Text Extraction

Supports three resume formats:

```python
def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":      → pdfplumber
    elif ext == ".docx":   → python-docx
    elif ext == ".txt":    → plain file read
```

**Why pdfplumber?**
- Pure Python library — no C compiler needed
- Works on all platforms including Windows with Python 3.13
- `PyMuPDF` (the popular alternative) requires a C compiler to build on Python 3.13

---

### `src/analyzer.py` — The AI Brain

This is the **most important file**. It sends the JD + resume to Gemini and gets structured JSON back.

#### Prompt Engineering
The prompt instructs Gemini to return **only valid JSON** with this structure:
```json
{
  "score": 7,
  "match_summary": "Good match with some skill gaps",
  "strengths": ["..."],
  "weaknesses": ["..."],
  "suggestions": ["..."],
  "missing_keywords": ["Docker", "CI/CD"]
}
```

#### Why JSON output?
- Structured data is easy to parse and format into a beautiful Telegram message
- Prevents Gemini from returning free-form text we can't split into sections

#### Score Bar
```python
def build_score_bar(score=8):
    # Returns: ████████░░ 8/10
    filled = "█" * score
    empty  = "░" * (10 - score)
```

#### Markdown Stripping for WhatsApp
Telegram supports `*bold*` and `_italic_` markdown. WhatsApp does not render the same syntax, so in `whatsapp_bot.py` we strip all `*`, `_`, `` ` `` before sending.

---

### `src/telegram_bot.py` — Telegram Handler

Built with **python-telegram-bot v21** using async/await:

```python
# Registers command handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("reset", reset))

# Registers message handlers
app.add_handler(MessageHandler(filters.Document.ALL, handle_document))  # file upload
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))  # text
```

**Flow:**
1. `/start` → resets session, sets state to `AWAITING_JD`
2. User sends text → if `AWAITING_JD`: save JD, move to `AWAITING_RESUME`
3. User sends file → download it, extract text, run analysis
4. Analysis result → sent back as a formatted multi-section Telegram message

**File download:**
```python
tg_file = await context.bot.get_file(doc.file_id)
await tg_file.download_to_drive(save_path)
# → extract text → delete local file
```

---

### `src/whatsapp_bot.py` — WhatsApp Webhook

Uses **Flask** to receive POST requests from Twilio when a user sends a WhatsApp message.

**How WhatsApp + Twilio works:**
1. User sends WhatsApp message → Twilio receives it
2. Twilio sends a POST request to your server's `/whatsapp` endpoint
3. Your Flask server processes it and replies

```python
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    from_number = request.form.get("From")   # User's WhatsApp number
    body = request.form.get("Body")          # Message text
    media_url = request.form.get("MediaUrl0") # File attachment URL
```

**File download from Twilio:**
Twilio sends media as a URL protected by Basic Auth (account SID + auth token):
```python
response = requests.get(media_url, auth=(account_sid, auth_token))
```

**Two-step reply for long analysis:**
- Immediately returns a TwiML response: `"🔍 Analyzing... please wait"`
- Then sends the full analysis separately via Twilio REST API (`_send_whatsapp()`)
- This is needed because Twilio has a 5-second response timeout for webhooks

---

## 🔄 End-to-End Flow Diagram

```
User (Telegram / WhatsApp)
        │
        │ /start
        ▼
  session_store: IDLE → AWAITING_JD
        │
        │ Pastes Job Description text
        ▼
  session_store: AWAITING_JD → AWAITING_RESUME
        │
        │ Uploads resume.pdf
        ▼
  file_handler.extract_text()   ← pdfplumber reads PDF
        │
        ▼
  analyzer.analyze_resume(jd, resume_text)
        │
        ▼
  Google Gemini API   ← structured JSON prompt
        │
        ▼
  Format result (score bar, sections)
        │
        ▼
  Send back to user
  session_store: DONE
```

---

## 🔐 Environment Variables (`.env`)

```env
TELEGRAM_BOT_TOKEN=...      # From @BotFather on Telegram
GEMINI_API_KEY=...          # From Google AI Studio (free)
TWILIO_ACCOUNT_SID=...      # From Twilio console
TWILIO_AUTH_TOKEN=...       # From Twilio console
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
FLASK_PORT=5000
```

---

## ❓ Common Interview Questions

**Q: Why did you choose Gemini over GPT?**
> Gemini 2.5 Flash has a generous free tier, is fast, and returns structured JSON reliably. GPT-4 requires a paid API.

**Q: How do you handle multiple users at the same time?**
> Each user gets their own entry in the `session_store` dict, keyed by their Telegram chat ID or WhatsApp phone number. The async nature of python-telegram-bot means many users can be served concurrently.

**Q: What happens if Gemini returns invalid JSON?**
> We wrap `json.loads()` in a try/except. If parsing fails, we send a friendly error message and let the user try again — the session stays in `AWAITING_RESUME` state.

**Q: Why Flask for WhatsApp and not Django?**
> Flask is lightweight and perfect for a single webhook endpoint. Django would be overkill here.

**Q: How would you scale this to production?**
> Replace the in-memory `dict` with Redis for session storage. Use a production WSGI server (Gunicorn) instead of Flask's dev server. Deploy on a cloud VM with a permanent public URL, removing the need for ngrok.

**Q: What is the Conflict error and how did you fix it?**
> Telegram only allows one active polling connection per bot token. Running two instances of `main.py` simultaneously causes a 409 Conflict. Fixed by always killing existing processes before restarting, and adding `drop_pending_updates=True` to clear stale connections on startup.
