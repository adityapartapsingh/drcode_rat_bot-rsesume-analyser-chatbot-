"""
analyzer.py
Uses Google Gemini to score a resume against a job description
and return structured feedback.
"""
import os
import json
import re
import google.generativeai as genai  # type: ignore
from dotenv import load_dotenv  # type: ignore

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-2.5-flash")


def build_score_bar(score: int, total: int = 10) -> str:
    filled = "█" * score
    empty = "░" * (total - score)
    return f"{filled}{empty} {score}/{total}"


def analyze_resume(job_description: str, resume_text: str) -> str:
    """
    Sends JD + resume to Gemini and returns a formatted analysis string.
    """
    prompt = f"""
You are an expert HR analyst and resume coach. Analyze the following resume against the given job description.

Return ONLY a valid JSON object (no markdown, no backticks, no explanation) with this exact structure:
{{
  "score": <integer from 1 to 10>,
  "match_summary": "<one sentence summary of overall fit>",
  "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "weaknesses": ["<weakness 1>", "<weakness 2>", "<weakness 3>"],
  "suggestions": [
    "<specific actionable suggestion 1>",
    "<specific actionable suggestion 2>",
    "<specific actionable suggestion 3>",
    "<specific actionable suggestion 4>"
  ],
  "missing_keywords": ["<keyword1>", "<keyword2>", "<keyword3>"]
}}

Scoring guide:
- 1-3: Poor match, major gaps
- 4-5: Below average, several missing areas
- 6-7: Good match with room for improvement
- 8-9: Strong match, minor gaps
- 10: Perfect match

JOB DESCRIPTION:
{job_description}

RESUME:
{resume_text}
"""

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # Strip markdown code blocks if present
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"^```\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return (
            "⚠️ I had trouble parsing the AI response. Please try again.\n\n"
            f"Raw response:\n{str(raw)[:500]}"  # type: ignore[index]


        )

    score = int(data.get("score", 0))
    score_bar = build_score_bar(score)
    match_summary = data.get("match_summary", "")
    strengths = data.get("strengths", [])
    weaknesses = data.get("weaknesses", [])
    suggestions = data.get("suggestions", [])
    missing_keywords = data.get("missing_keywords", [])

    # Emoji for score
    if score >= 8:
        score_emoji = "🌟"
    elif score >= 6:
        score_emoji = "✅"
    elif score >= 4:
        score_emoji = "⚠️"
    else:
        score_emoji = "❌"

    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 *RESUME ANALYSIS REPORT*",
        f"━━━━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"{score_emoji} *Score: {score_bar}*",
        f"",
        f"📝 _{match_summary}_",
        f"",
    ]

    if strengths:
        lines.append("✅ *Strengths:*")
        for s in strengths:
            lines.append(f"  • {s}")
        lines.append("")

    if weaknesses:
        lines.append("⚠️ *Weaknesses:*")
        for w in weaknesses:
            lines.append(f"  • {w}")
        lines.append("")

    if missing_keywords:
        lines.append("🔍 *Missing Keywords:*")
        lines.append(f"  `{', '.join(missing_keywords)}`")
        lines.append("")

    if suggestions:
        lines.append("💡 *Suggestions to Improve:*")
        for i, sug in enumerate(suggestions, 1):
            lines.append(f"  {i}. {sug}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💬 *You can now ask follow-up questions* (e.g. \"How to improve my summary?\")")
    lines.append("🔄 Type /reset to analyze a new resume.")

    return "\n".join(lines)


def ask_followup(job_description: str, resume_text: str, question: str) -> str:
    """
    Handles follow-up questions after the initial analysis using stateless context.
    """
    prompt = f"""
You are an expert HR analyst and resume coach. 
The user has previously provided their resume and a job description. 
They are now asking a follow-up question regarding how to improve their resume, interview tips, or specific details.

JOB DESCRIPTION:
{job_description}

RESUME:
{resume_text}

USER'S QUESTION:
{question}

Answer the question directly, concisely, and professionally. Do not use JSON. Use simple markdown.
"""
    response = model.generate_content(prompt)
    return response.text.strip()

