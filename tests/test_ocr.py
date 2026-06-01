"""Unit tests for pyads.ocr — fully offline, Mistral client is mocked."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads import ocr as ocr_module  # noqa: E402


def _make_mistral_mock(pages_markdown: list[str], usage: dict | None = None) -> MagicMock:
    """Build a Mistral client mock that simulates an OCR response."""
    uploaded = MagicMock()
    uploaded.id = "file-test-123"

    signed_url = MagicMock()
    signed_url.url = "https://example.com/signed-url"

    mock_pages = []
    for md in pages_markdown:
        page = MagicMock()
        page.markdown = md
        mock_pages.append(page)

    usage_obj = MagicMock()
    usage_obj.model_dump.return_value = usage or {"pages_processed": len(pages_markdown), "doc_size_bytes": 512}

    pdf_response = MagicMock()
    pdf_response.pages = mock_pages
    pdf_response.usage_info = usage_obj

    client = MagicMock()
    client.files.upload.return_value = uploaded
    client.files.get_signed_url.return_value = signed_url
    client.ocr.process.return_value = pdf_response
    return client


class ExtractTextFromPdfTests(unittest.TestCase):
    """Tests for extract_text_from_pdf."""

    def setUp(self):
        """Create a minimal temporary PDF file for each test."""
        self._tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        self._tmp.write(b"%PDF-1.4 minimal test file")
        self._tmp.flush()
        self._pdf_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.close()
        self._pdf_path.unlink(missing_ok=True)

    @patch("pyads.ocr.MISTRAL_API_KEY", "test-key-12345")
    @patch("pyads.ocr.Mistral")
    def test_returns_concatenated_page_text(self, mock_cls):
        mock_cls.return_value = _make_mistral_mock(["# Page 1", "## Page 2"])
        result = ocr_module.extract_text_from_pdf(self._pdf_path)
        self.assertIn("Page 1", result)
        self.assertIn("Page 2", result)

    @patch("pyads.ocr.MISTRAL_API_KEY", "test-key-12345")
    @patch("pyads.ocr.Mistral")
    def test_returns_usage_when_requested(self, mock_cls):
        mock_cls.return_value = _make_mistral_mock(
            ["Content"],
            usage={"pages_processed": 1, "doc_size_bytes": 256},
        )
        text, usage = ocr_module.extract_text_from_pdf(self._pdf_path, return_usage=True)
        self.assertIsNotNone(text)
        self.assertEqual(usage.get("pages_processed"), 1)

    @patch("pyads.ocr.MISTRAL_API_KEY", "")
    def test_returns_none_when_api_key_missing(self):
        result = ocr_module.extract_text_from_pdf(self._pdf_path)
        self.assertIsNone(result)

    @patch("pyads.ocr.MISTRAL_API_KEY", "")
    def test_returns_none_usage_tuple_when_api_key_missing(self):
        text, usage = ocr_module.extract_text_from_pdf(self._pdf_path, return_usage=True)
        self.assertIsNone(text)
        self.assertEqual(usage, {})

    @patch("pyads.ocr.MISTRAL_API_KEY", "test-key-12345")
    @patch("pyads.ocr.Mistral")
    def test_returns_none_on_exception(self, mock_cls):
        client = MagicMock()
        client.files.upload.side_effect = RuntimeError("network error")
        mock_cls.return_value = client
        result = ocr_module.extract_text_from_pdf(self._pdf_path)
        self.assertIsNone(result)


class ProcessPdfsTests(unittest.TestCase):
    """Tests for process_pdfs batch processing."""

    def test_returns_empty_dict_when_pdf_dir_missing(self):
        result = ocr_module.process_pdfs(
            pdf_dir=Path("/nonexistent/path/that/does/not/exist"),
            text_dir=Path(tempfile.mkdtemp()),
        )
        self.assertEqual(result, {})

    def test_returns_empty_dict_when_no_pdfs_found(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = ocr_module.process_pdfs(
                pdf_dir=Path(tmp_dir),
                text_dir=Path(tmp_dir),
            )
        self.assertEqual(result, {})

    @patch("pyads.ocr.MISTRAL_API_KEY", "test-key-12345")
    @patch("pyads.ocr.extract_text_from_pdf")
    def test_writes_txt_file_for_each_pdf(self, mock_extract):
        mock_extract.return_value = ("Extracted text content", {"pages_processed": 1})
        with tempfile.TemporaryDirectory() as pdf_dir, \
                tempfile.TemporaryDirectory() as text_dir:
            pdf_path = Path(pdf_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")
            ocr_module.process_pdfs(
                pdf_dir=Path(pdf_dir),
                text_dir=Path(text_dir),
            )
            txt_path = Path(text_dir) / "paper.txt"
            self.assertTrue(txt_path.exists())
            self.assertEqual(txt_path.read_text(encoding="utf-8"), "Extracted text content")


if __name__ == "__main__":
    unittest.main()
