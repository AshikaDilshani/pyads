"""OCR module: extract text from PDFs using the Mistral OCR API."""

import logging
from pathlib import Path

try:
    from mistralai import DocumentURLChunk, Mistral
except ImportError:
    from mistralai.client import Mistral
    DocumentURLChunk = None

from pyads.config import LOG_LEVEL, MISTRAL_API_KEY, PDF_DIR, TEXT_DIR


def _setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def _page_markdown(page: object) -> str:
    if isinstance(page, dict):
        return page.get("markdown", "")
    return getattr(page, "markdown", "") or ""


def _ocr_usage_dict(pdf_response: object) -> dict:
    usage = getattr(pdf_response, "usage_info", None)
    if usage is None and isinstance(pdf_response, dict):
        usage = pdf_response.get("usage_info")
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return dict(usage)


def extract_text_from_pdf(pdf_path: Path, return_usage: bool = False):
    """Upload a PDF to Mistral OCR and return the extracted markdown text.

    Returns a (text, usage) tuple when *return_usage* is True, otherwise just the text.
    Returns None (or (None, {})) on failure.
    """
    if not MISTRAL_API_KEY:
        logging.error(
            "MISTRAL_API_KEY not set. Define it in .env as MISTRAL_API_KEY=..."
        )
        return (None, {}) if return_usage else None
    try:
        client = Mistral(api_key=MISTRAL_API_KEY)
        pdf_file = Path(pdf_path)
        uploaded_file = client.files.upload(
            file={
                "file_name": pdf_file.name,
                "content": pdf_file.read_bytes(),
            },
            purpose="ocr",
        )
        signed_url = client.files.get_signed_url(file_id=uploaded_file.id, expiry=1)
        document = (
            DocumentURLChunk(document_url=signed_url.url)
            if DocumentURLChunk is not None
            else {"type": "document_url", "document_url": signed_url.url}
        )
        pdf_response = client.ocr.process(
            model="mistral-ocr-latest",
            document=document,
            include_image_base64=False,
        )
        pages = getattr(pdf_response, "pages", None)
        if pages is None and isinstance(pdf_response, dict):
            pages = pdf_response.get("pages", [])
        text = "\n\n".join(_page_markdown(page) for page in pages or [])
        usage = _ocr_usage_dict(pdf_response)
        return (text, usage) if return_usage else text
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logging.error("Failed to process %s: %s", pdf_path, exc)
        return (None, {}) if return_usage else None


def process_pdfs(pdf_dir: Path = PDF_DIR, text_dir: Path = TEXT_DIR) -> dict:
    """Process all PDFs in *pdf_dir*, write extracted text to *text_dir*.

    Returns an aggregated usage dict with pages_processed and doc_size_bytes.
    """
    _setup_logging()
    pdf_dir = Path(pdf_dir)
    text_dir = Path(text_dir)
    text_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_dir.exists():
        logging.warning("PDF directory %s does not exist.", pdf_dir)
        return {}

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        logging.warning("No PDF files found in %s.", pdf_dir)
        return {}

    total_usage: dict = {"pages_processed": 0, "doc_size_bytes": 0}
    for pdf_path in pdf_files:
        logging.info("Processing %s", pdf_path.name)
        text, usage = extract_text_from_pdf(pdf_path, return_usage=True)
        for key in total_usage:
            total_usage[key] += int(usage.get(key) or 0)
        if text:
            text_path = text_dir / f"{pdf_path.stem}.txt"
            text_path.write_text(text, encoding="utf-8")
            logging.info("Saved text to %s", text_path)
        else:
            logging.warning("No text extracted from %s", pdf_path.name)

    return total_usage
