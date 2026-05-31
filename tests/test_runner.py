"""Unit tests for pyads.runner — offline, no network or API calls."""

import sys
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


if __name__ == "__main__":
    unittest.main()
