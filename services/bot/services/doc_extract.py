"""Извлечение текста из PDF и DOCX."""
import structlog

log = structlog.get_logger()
MAX_EXTRACT_CHARS = 80_000


def extract_text_from_pdf(bytes_data: bytes) -> str:
    try:
        import pymupdf
        doc = pymupdf.open(stream=bytes_data, filetype="pdf")
        parts = []
        for page in doc:
            parts.append(page.get_text())
        doc.close()
        text = "\n".join(parts).strip()
        return text[:MAX_EXTRACT_CHARS] if len(text) > MAX_EXTRACT_CHARS else text
    except Exception as e:
        log.warning("PDF extract failed", error=str(e))
        return ""


def extract_text_from_docx(bytes_data: bytes) -> str:
    try:
        from io import BytesIO

        from docx import Document
        doc = Document(BytesIO(bytes_data))
        parts = [p.text for p in doc.paragraphs]
        text = "\n".join(parts).strip()
        return text[:MAX_EXTRACT_CHARS] if len(text) > MAX_EXTRACT_CHARS else text
    except Exception as e:
        log.warning("DOCX extract failed", error=str(e))
        return ""


def extract_text_from_file(filename: str, bytes_data: bytes) -> tuple[str, str | None]:
    """
    Возвращает (извлечённый текст, error_message).
    error_message не None при неподдерживаемом формате или ошибке.
    """
    fn = (filename or "").lower()
    if fn.endswith(".pdf"):
        text = extract_text_from_pdf(bytes_data)
        if not text:
            return "", "Не удалось извлечь текст из PDF."
        return text, None
    if fn.endswith(".docx") or fn.endswith(".doc"):
        if fn.endswith(".doc"):
            return "", "Поддерживается только .docx (не .doc)."
        text = extract_text_from_docx(bytes_data)
        if not text:
            return "", "Не удалось извлечь текст из DOCX."
        return text, None
    return "", "Поддерживаются только PDF и DOCX."
