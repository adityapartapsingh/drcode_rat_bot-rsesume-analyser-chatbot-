"""
file_handler.py
Extracts plain text from PDF, DOCX, or plain text files.
"""
import os
import tempfile


def extract_text_from_pdf(file_path: str) -> str:
    try:
        import pdfplumber  # type: ignore
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts).strip()
    except Exception as e:
        raise ValueError(f"Failed to read PDF: {e}")


def extract_text_from_docx(file_path: str) -> str:
    try:
        from docx import Document  # type: ignore
        doc = Document(file_path)
        text = "\n".join(para.text for para in doc.paragraphs)
        return text.strip()
    except Exception as e:
        raise ValueError(f"Failed to read DOCX: {e}")


def extract_text(file_path: str) -> str:
    """Auto-detect file type and extract text."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in (".docx", ".doc"):
        return extract_text_from_docx(file_path)
    elif ext in (".txt", ""):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    else:
        raise ValueError(f"Unsupported file type: {ext}. Please send a PDF, DOCX, or TXT file.")
