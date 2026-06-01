"""Unit tests for pyads.runner — offline, no network or API calls."""

import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads import runner as runner_module  # noqa: E402


class RunnerTests(unittest.TestCase):
    """Tests for CLI argument parsing and pipeline stage orchestration."""

    def test_parse_args_skips_are_false_by_default(self):
        args = runner_module.parse_args([])

        self.assertFalse(args.skip_ocr)
        self.assertFalse(args.skip_extraction)
        self.assertFalse(args.skip_cif_download)
        self.assertFalse(args.skip_cif_analysis)
        self.assertFalse(args.second_pass)

    def test_main_respects_skip_flags(self):
        argv = [
            "--skip-ocr",
            "--skip-extraction",
            "--skip-cif-download",
            "--skip-cif-analysis",
        ]
        with patch.object(runner_module, "run_ocr") as run_ocr, \
             patch.object(runner_module, "run_extraction") as run_extraction, \
             patch.object(runner_module, "run_cif_download") as run_cif_download, \
             patch.object(runner_module, "run_cif_analysis") as run_cif_analysis:
            with redirect_stdout(StringIO()):
                runner_module.main(argv)

        run_ocr.assert_not_called()
        run_extraction.assert_not_called()
        run_cif_download.assert_not_called()
        run_cif_analysis.assert_not_called()

    def test_main_runs_stages_in_order_when_not_skipped(self):
        calls = []

        def record_call(name):
            def _inner(*_args, **_kwargs):
                calls.append(name)
            return _inner

        with patch.object(runner_module, "run_ocr", side_effect=record_call("ocr")), \
             patch.object(runner_module, "run_extraction", side_effect=record_call("extraction")), \
             patch.object(runner_module, "run_cif_download", side_effect=record_call("cif_download")), \
             patch.object(runner_module, "run_cif_analysis", side_effect=record_call("cif_analysis")):
            with redirect_stdout(StringIO()):
                runner_module.main([])

        self.assertEqual(calls, ["ocr", "extraction", "cif_download", "cif_analysis"])

    def test_run_extraction_passes_second_pass_flag(self):
        args = Mock()
        args.text_dir = "text"
        args.output_dir = "out"
        args.model = "model"
        args.max_chars = 100
        args.validation_max_chars = 50
        args.second_pass = True
        args.limit = 1
        args.agentic = False

        fake_outputs = {"json": "data.json", "excel": "data.xlsx", "usage": "usage.json"}
        fake_usage = {"total": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}
        mock_ptf = Mock(return_value=([], fake_outputs, fake_usage))

        with patch.object(runner_module, "process_text_files", mock_ptf):
            with redirect_stdout(StringIO()):
                runner_module.run_extraction(args)

        mock_ptf.assert_called_once_with(
            text_dir="text",
            output_dir="out",
            model="model",
            max_chars=100,
            validation_max_chars=50,
            second_pass=True,
            limit=1,
        )


class DryRunTests(unittest.TestCase):
    """Tests for the --dry-run flag in main."""

    def test_dry_run_lists_pdfs_without_calling_stages(self):
        with tempfile.TemporaryDirectory() as pdf_dir:
            pdf_path = Path(pdf_dir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test")

            with patch.object(runner_module, "run_ocr") as run_ocr, \
                    patch.object(runner_module, "run_extraction") as run_extraction:
                output = StringIO()
                with redirect_stdout(output):
                    runner_module.main(["--dry-run", "--pdf-dir", pdf_dir])

        run_ocr.assert_not_called()
        run_extraction.assert_not_called()
        self.assertIn("paper.pdf", output.getvalue())

    def test_dry_run_raises_when_no_pdfs(self):
        with tempfile.TemporaryDirectory() as empty_dir:
            with self.assertRaises(FileNotFoundError):
                runner_module.main(["--dry-run", "--pdf-dir", empty_dir])

    def test_dry_run_raises_when_dir_missing(self):
        with self.assertRaises(FileNotFoundError):
            runner_module.main(["--dry-run", "--pdf-dir", "/nonexistent/path"])


class MaybePrintTokenCostTests(unittest.TestCase):
    """Tests for the optional Mistral cost estimation output."""

    def test_prints_nothing_when_no_tokens(self):
        usage = {"total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        output = StringIO()
        with redirect_stdout(output):
            runner_module._maybe_print_token_cost(usage)
        self.assertEqual(output.getvalue(), "")

    def test_prints_nothing_when_prices_not_set(self):
        usage = {"total": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}}
        env_without_prices = {k: v for k, v in os.environ.items()
                              if k not in ("MISTRAL_PROMPT_PRICE_PER_MTOK",
                                           "MISTRAL_COMPLETION_PRICE_PER_MTOK")}
        with patch.dict(os.environ, env_without_prices, clear=True):
            output = StringIO()
            with redirect_stdout(output):
                runner_module._maybe_print_token_cost(usage)
        self.assertEqual(output.getvalue(), "")

    def test_prints_cost_when_prices_are_set(self):
        usage = {"total": {"prompt_tokens": 1_000_000, "completion_tokens": 0, "total_tokens": 1_000_000}}
        with patch.dict(os.environ, {"MISTRAL_PROMPT_PRICE_PER_MTOK": "0.5",
                                      "MISTRAL_COMPLETION_PRICE_PER_MTOK": "0.0"}):
            output = StringIO()
            with redirect_stdout(output):
                runner_module._maybe_print_token_cost(usage)
        self.assertIn("0.5", output.getvalue())


class ParseArgsTests(unittest.TestCase):
    """Additional argument parsing tests."""

    def test_second_pass_flag_defaults_to_false(self):
        args = runner_module.parse_args([])
        self.assertFalse(args.second_pass)

    def test_agentic_flag_can_be_set(self):
        args = runner_module.parse_args(["--agentic"])
        self.assertTrue(args.agentic)

    def test_limit_is_none_by_default(self):
        args = runner_module.parse_args([])
        self.assertIsNone(args.limit)

    def test_limit_can_be_set(self):
        args = runner_module.parse_args(["--limit", "3"])
        self.assertEqual(args.limit, 3)

    def test_dry_run_defaults_to_false(self):
        args = runner_module.parse_args([])
        self.assertFalse(args.dry_run)


if __name__ == "__main__":
    unittest.main()
