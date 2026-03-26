"""
session_store.py
Tracks per-user conversation state across Telegram and WhatsApp.
"""

# States
IDLE = "IDLE"
AWAITING_JD = "AWAITING_JD"
AWAITING_RESUME = "AWAITING_RESUME"
ANALYZING = "ANALYZING"
DONE = "DONE"

# In-memory store: { user_key: { "state": ..., "jd": ..., "resume": ... } }
_sessions: dict = {}


def get_session(user_key: str) -> dict:
    if user_key not in _sessions:
        _sessions[user_key] = {"state": IDLE, "jd": None, "resume": None}
    return _sessions[user_key]


def set_state(user_key: str, state: str):
    get_session(user_key)["state"] = state


def set_jd(user_key: str, jd: str):
    get_session(user_key)["jd"] = jd


def set_resume(user_key: str, resume: str):
    get_session(user_key)["resume"] = resume


def reset_session(user_key: str):
    _sessions[user_key] = {"state": IDLE, "jd": None, "resume": None}
