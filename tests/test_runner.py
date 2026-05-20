import importlib.util
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_ROOT / "runner.py"


def load_runner_module():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    spec = importlib.util.spec_from_file_location("runner", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.runner = load_runner_module()

    def test_parse_args_skips_are_false_by_default(self):
        with patch.object(sys, "argv", ["runner.py"]):
            args = self.runner.parse_args()

        self.assertFalse(args.skip_ocr)
        self.assertFalse(args.skip_extraction)
        self.assertFalse(args.skip_cif_download)
        self.assertFalse(args.skip_cif_analysis)
        self.assertFalse(args.second_pass)

    def test_main_respects_skip_flags(self):
        with patch.object(
            sys,
            "argv",
            ["runner.py", "--skip-ocr", "--skip-extraction", "--skip-cif-download", "--skip-cif-analysis"],
        ), patch.object(self.runner, "run_ocr") as run_ocr, patch.object(
            self.runner, "run_extraction"
        ) as run_extraction, patch.object(
            self.runner, "run_cif_download"
        ) as run_cif_download, patch.object(
            self.runner, "run_cif_analysis"
        ) as run_cif_analysis:
            with redirect_stdout(StringIO()):
                self.runner.main()

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

        with patch.object(sys, "argv", ["runner.py"]), patch.object(
            self.runner, "run_ocr", side_effect=record_call("ocr")
        ), patch.object(
            self.runner, "run_extraction", side_effect=record_call("extraction")
        ), patch.object(
            self.runner, "run_cif_download", side_effect=record_call("cif_download")
        ), patch.object(
            self.runner, "run_cif_analysis", side_effect=record_call("cif_analysis")
        ):
            with redirect_stdout(StringIO()):
                self.runner.main()

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
        fake_extractor_module = Mock(process_text_files=Mock(return_value=([], fake_outputs, fake_usage)))

        with patch.dict(
            sys.modules,
            {"pyads.extractor": fake_extractor_module},
        ):
            with redirect_stdout(StringIO()):
                self.runner.run_extraction(args)

        fake_extractor_module.process_text_files.assert_called_once_with(
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
