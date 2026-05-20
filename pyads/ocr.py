"""
OCR module for extracting text from PDFs using Mistral OCR API.
"""

import os
import logging
from pathlib import Path

try:
    from mistralai import Mistral, DocumentURLChunk
except ImportError:
    from mistralai.client import Mistral
    DocumentURLChunk = None

from pyads.config import MISTRAL_API_KEY, LOG_LEVEL, PDF_DIR, TEXT_DIR

def setup_logging():
    """Set up logging based on config."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )


def _page_markdown(page):
    if isinstance(page, dict):
        return page.get("markdown", "")
    return getattr(page, "markdown", "") or ""


def _ocr_usage_dict(pdf_response):
    usage = getattr(pdf_response, "usage_info", None)
    if usage is None and isinstance(pdf_response, dict):
        usage = pdf_response.get("usage_info")
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return dict(usage)


def extract_text_from_pdf(pdf_path, return_usage=False):
    """Extract text from a PDF using Mistral OCR API."""
    if not MISTRAL_API_KEY:
        logging.error("MISTRAL_API_KEY not set.")
        return (None, {}) if return_usage else None
    try:
        client = Mistral(api_key=MISTRAL_API_KEY)
        pdf_file = Path(pdf_path)
        # Upload PDF file
        uploaded_file = client.files.upload(
            file={
                "file_name": pdf_file.name,
                "content": pdf_file.read_bytes(),
            },
            purpose="ocr",
        )
        # Get signed URL
        signed_url = client.files.get_signed_url(file_id=uploaded_file.id, expiry=1)
        # Process OCR
        document = (
            DocumentURLChunk(document_url=signed_url.url)
            if DocumentURLChunk is not None
            else {"type": "document_url", "document_url": signed_url.url}
        )
        pdf_response = client.ocr.process(
            model="mistral-ocr-latest",
            document=document,
            include_image_base64=False
        )
        # Parse response
        pages = getattr(pdf_response, "pages", None)
        if pages is None and isinstance(pdf_response, dict):
            pages = pdf_response.get("pages", [])
        text = '\n\n'.join(_page_markdown(page) for page in pages or [])
        usage = _ocr_usage_dict(pdf_response)
        return (text, usage) if return_usage else text
    except Exception as e:
        logging.error(f"Failed to process {pdf_path}: {str(e)}")
        return (None, {}) if return_usage else None

def process_pdfs(pdf_dir=PDF_DIR, text_dir=TEXT_DIR):
    """Process all PDFs, extract text with Mistral OCR, and save text files."""
    setup_logging()
    pdf_dir = Path(pdf_dir)
    text_dir = Path(text_dir)
    os.makedirs(text_dir, exist_ok=True)
    if not pdf_dir.exists():
        logging.warning(f"PDF directory {pdf_dir} does not exist.")
        return {}

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        logging.warning(f"No PDF files found in {pdf_dir}.")
        return {}

    total_usage = {"pages_processed": 0, "doc_size_bytes": 0}
    for pdf_path in pdf_files:
        logging.info(f"Processing {pdf_path.name}")
        text, usage = extract_text_from_pdf(pdf_path, return_usage=True)
        for key in total_usage:
            total_usage[key] += int(usage.get(key) or 0)
        if text:
            text_path = text_dir / f"{pdf_path.stem}.txt"
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write(text)
            logging.info(f"Saved text to {text_path}")
        else:
            logging.warning(f"No text extracted from {pdf_path.name}")

    return total_usage
