"""Unit tests for pyads.extractor — offline, Mistral client is fully mocked."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads import extractor  # noqa: E402


def _make_mock_client(response_json: str) -> MagicMock:
    """Return a Mistral client mock that returns *response_json* as the LLM reply."""
    mock_message = MagicMock()
    mock_message.content = response_json

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_usage = MagicMock()
    mock_usage.model_dump.return_value = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    mock_client = MagicMock()
    mock_client.chat.complete.return_value = mock_response
    return mock_client


class ParseJsonTests(unittest.TestCase):
    """Tests for the internal JSON-cleaning helper."""

    def test_parses_plain_json(self):
        raw = '{"material": "ZIF-8", "year": 2020}'
        result = extractor._parse_json(raw)
        self.assertEqual(result["material"], "ZIF-8")

    def test_strips_markdown_fences(self):
        raw = "```json\n{\"material\": \"MOF-5\"}\n```"
        result = extractor._parse_json(raw)
        self.assertEqual(result["material"], "MOF-5")

    def test_extracts_json_from_surrounding_text(self):
        raw = 'Here is the result: {"year": 2021} — end.'
        result = extractor._parse_json(raw)
        self.assertEqual(result["year"], 2021)


class NormalizeRecordTests(unittest.TestCase):
    """Tests for schema normalization of raw LLM output."""

    def _normalize(self, raw: dict) -> dict:
        return extractor._normalize_record(raw, "test.txt")

    def test_valid_surface_area_is_kept(self):
        record = self._normalize({"surface_area": {"value": 1500, "unit": "m2/g"}})
        self.assertEqual(record["surface_area"]["value"], 1500)
        self.assertEqual(record["surface_area"]["unit"], "m2/g")

    def test_pore_volume_with_wrong_unit_is_cleared(self):
        # cm3/g is valid for pore volume but NOT for surface area
        record = self._normalize({"surface_area": {"value": 0.5, "unit": "cm3/g"}})
        self.assertIsNone(record["surface_area"]["value"])

    def test_valid_pore_volume_is_kept(self):
        record = self._normalize({"pore_volume": {"value": 0.55, "unit": "cm3/g"}})
        self.assertEqual(record["pore_volume"]["value"], 0.55)

    def test_duplicate_temperatures_are_deduplicated(self):
        raw = {
            "isotherm_temperatures": [
                {"value": 298, "unit": "K"},
                {"value": 298, "unit": "K"},
                {"value": 273, "unit": "K"},
            ]
        }
        record = self._normalize(raw)
        self.assertEqual(len(record["isotherm_temperatures"]), 2)

    def test_gases_coerced_to_list_when_string(self):
        record = self._normalize({"gases": "CO2"})
        self.assertIsInstance(record["gases"], list)
        self.assertIn("CO2", record["gases"])

    def test_source_file_is_set(self):
        record = self._normalize({})
        self.assertEqual(record["source_file"], "test.txt")

    def test_schema_version_is_always_1(self):
        record = self._normalize({})
        self.assertEqual(record["schema_version"], 1)


class ExtractDataFromTextTests(unittest.TestCase):
    """Integration-style tests for extract_data_from_text with a mocked client."""

    _RESPONSE = json.dumps({
        "doi": "10.1000/xyz123",
        "title": "CO2 capture with ZIF-8",
        "year": 2023,
        "material": "ZIF-8",
        "surface_area": {"value": 1200, "unit": "m2/g"},
        "pore_volume": {"value": 0.55, "unit": "cm3/g"},
        "pore_size": {"value": 3.4, "unit": "Å"},
        "gases": ["CO2", "N2"],
        "isotherm_temperatures": [
            {"value": 273, "unit": "K"},
            {"value": 298, "unit": "K"},
        ],
    })

    def test_returns_normalized_record_and_usage(self):
        client = _make_mock_client(self._RESPONSE)
        ocr_text = "BET surface area 1200 m2/g. CO2 adsorption at 298 K."

        record, usage = extractor.extract_data_from_text(
            ocr_text, "paper.txt", client, "mistral-small-latest"
        )

        self.assertEqual(record["material"], "ZIF-8")
        self.assertEqual(record["surface_area"]["value"], 1200)
        self.assertEqual(record["surface_area"]["unit"], "m2/g")
        self.assertEqual(record["gases"], ["CO2", "N2"])
        self.assertEqual(len(record["isotherm_temperatures"]), 2)
        self.assertEqual(usage["total_tokens"], 150)

    def test_llm_is_called_once_per_extraction(self):
        client = _make_mock_client(self._RESPONSE)
        extractor.extract_data_from_text("some text", "f.txt", client, "mistral-small-latest")
        client.chat.complete.assert_called_once()


class RetryLogicTests(unittest.TestCase):
    """Tests for _chat_json_with_retries rate-limit handling."""

    @staticmethod
    def _ok_response(content: str) -> MagicMock:
        msg = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        usage = MagicMock()
        usage.model_dump.return_value = {
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15
        }
        response = MagicMock()
        response.choices = [choice]
        response.usage = usage
        return response

    def test_raises_immediately_on_non_rate_limit_error(self):
        client = MagicMock()
        client.chat.complete.side_effect = ValueError("bad model")
        with self.assertRaises(ValueError):
            extractor._chat_json_with_retries(
                client, "mistral-small-latest", "prompt", "system", retries=2, base_delay=0
            )
        self.assertEqual(client.chat.complete.call_count, 1)

    def test_retries_on_rate_limit_then_succeeds(self):
        client = MagicMock()
        client.chat.complete.side_effect = [
            Exception("status 429: rate limit"),
            self._ok_response('{"material": "ZIF-8"}'),
        ]
        from unittest.mock import patch  # pylint: disable=import-outside-toplevel
        with patch("pyads.extractor.time.sleep"):
            result, _ = extractor._chat_json_with_retries(
                client, "mistral-small-latest", "prompt", "system", retries=2, base_delay=0
            )
        self.assertEqual(result.get("material"), "ZIF-8")
        self.assertEqual(client.chat.complete.call_count, 2)

    def test_raises_after_exhausting_retries(self):
        client = MagicMock()
        client.chat.complete.side_effect = Exception("status 429: rate limit")
        from unittest.mock import patch  # pylint: disable=import-outside-toplevel
        with patch("pyads.extractor.time.sleep"), self.assertRaises(Exception):
            extractor._chat_json_with_retries(
                client, "mistral-small-latest", "prompt", "system", retries=1, base_delay=0
            )
        self.assertEqual(client.chat.complete.call_count, 2)


class EvidenceTextTests(unittest.TestCase):
    """Tests for keyword-focused text truncation."""

    def test_short_text_is_returned_unchanged(self):
        text = "BET surface area 1000 m2/g"
        result = extractor._evidence_text(text, max_chars=10000)
        self.assertEqual(result, text)

    def test_long_text_is_truncated_to_max_chars(self):
        long_text = ("irrelevant filler\n\n" * 500) + "BET surface area 1200 m2/g"
        result = extractor._evidence_text(long_text, max_chars=500)
        self.assertLessEqual(len(result), 500)


class ValidateRecordFromTextTests(unittest.TestCase):
    """Direct tests for the strict second-pass validation function."""

    _CORRECTED_RESPONSE = json.dumps({
        "doi": "10.1000/test",
        "title": "Validated Paper",
        "year": 2024,
        "material": "ZIF-8",
        "surface_area": {"value": 1600.0, "unit": "m2/g"},
        "pore_volume": {"value": 0.636, "unit": "cm3/g"},
        "pore_size": {"value": 3.4, "unit": "Å"},
        "gases": ["CO2"],
        "isotherm_temperatures": [{"value": 298, "unit": "K"}],
    })

    def test_returns_normalized_corrected_record(self):
        client = _make_mock_client(self._CORRECTED_RESPONSE)
        first_record = extractor._empty_record("paper.txt")
        first_record["surface_area"] = {"value": 0.5, "unit": "cm3/g"}

        corrected, usage = extractor.validate_record_from_text(
            first_record, "BET surface area 1600 m2/g.", client, "mistral-small-latest"
        )

        self.assertEqual(corrected["material"], "ZIF-8")
        self.assertEqual(corrected["surface_area"]["value"], 1600.0)
        self.assertEqual(corrected["surface_area"]["unit"], "m2/g")
        self.assertEqual(usage["total_tokens"], 150)

    def test_llm_is_called_once_per_validation(self):
        client = _make_mock_client(self._CORRECTED_RESPONSE)
        record = extractor._empty_record("paper.txt")

        extractor.validate_record_from_text(
            record, "some OCR text", client, "mistral-small-latest"
        )

        client.chat.complete.assert_called_once()

    def test_schema_version_preserved_after_correction(self):
        client = _make_mock_client(self._CORRECTED_RESPONSE)
        record = extractor._empty_record("paper.txt")

        corrected, _ = extractor.validate_record_from_text(
            record, "some OCR text", client, "mistral-small-latest"
        )

        self.assertEqual(corrected["schema_version"], 1)


class SaveOutputsTests(unittest.TestCase):
    """Tests for save_outputs: file creation and content correctness."""

    def _sample_record(self):
        rec = extractor._empty_record("paper.txt")
        rec["material"] = "ZIF-8"
        rec["surface_area"] = {"value": 1200.0, "unit": "m2/g"}
        rec["gases"] = ["CO2"]
        return rec

    def test_creates_json_excel_and_usage_files(self):
        records = [self._sample_record()]
        usage = {"total": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}

        with tempfile.TemporaryDirectory() as output_dir:
            outputs = extractor.save_outputs(records, usage, output_dir)

            self.assertTrue(Path(outputs["json"]).exists())
            self.assertTrue(Path(outputs["excel"]).exists())
            self.assertTrue(Path(outputs["usage"]).exists())

    def test_json_contains_all_records(self):
        records = [self._sample_record(), self._sample_record()]
        usage = {"total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

        with tempfile.TemporaryDirectory() as output_dir:
            outputs = extractor.save_outputs(records, usage, output_dir)
            saved = json.loads(Path(outputs["json"]).read_text(encoding="utf-8"))

        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]["material"], "ZIF-8")

    def test_json_records_preserve_schema_version(self):
        records = [self._sample_record()]
        usage = {"total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

        with tempfile.TemporaryDirectory() as output_dir:
            outputs = extractor.save_outputs(records, usage, output_dir)
            saved = json.loads(Path(outputs["json"]).read_text(encoding="utf-8"))

        self.assertEqual(saved[0]["schema_version"], 1)

    def test_output_dir_is_created_if_missing(self):
        records = [self._sample_record()]
        usage = {"total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

        with tempfile.TemporaryDirectory() as base_dir:
            output_dir = Path(base_dir) / "nested" / "outputs"
            extractor.save_outputs(records, usage, output_dir)
            self.assertTrue(output_dir.exists())


class ProcessTextFilesTests(unittest.TestCase):
    """End-to-end tests for process_text_files with a mocked Mistral client."""

    _LLM_RESPONSE = json.dumps({
        "doi": "10.1/test",
        "title": "CO2 on ZIF-8",
        "year": 2023,
        "material": "ZIF-8",
        "surface_area": {"value": 1630.0, "unit": "m2/g"},
        "pore_volume": {"value": 0.636, "unit": "cm3/g"},
        "pore_size": {"value": 3.4, "unit": "Å"},
        "gases": ["CO2"],
        "isotherm_temperatures": [{"value": 298, "unit": "K"}],
    })

    def _setup_dirs(self, text_content="BET surface area 1630 m2/g at 298 K."):
        tmp = tempfile.mkdtemp()
        text_dir = Path(tmp) / "text"
        output_dir = Path(tmp) / "output"
        text_dir.mkdir()
        (text_dir / "paper.txt").write_text(text_content, encoding="utf-8")
        return text_dir, output_dir

    def test_extracts_one_record_from_one_text_file(self):
        text_dir, output_dir = self._setup_dirs()
        client = _make_mock_client(self._LLM_RESPONSE)

        with patch("pyads.extractor.MISTRAL_API_KEY", "test-key"), \
                patch("pyads.extractor.Mistral", return_value=client):
            records, outputs, _ = extractor.process_text_files(
                text_dir=text_dir,
                output_dir=output_dir,
                second_pass=False,
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["material"], "ZIF-8")
        self.assertTrue(Path(outputs["json"]).exists())

    def test_second_pass_calls_llm_twice(self):
        text_dir, output_dir = self._setup_dirs()
        client = _make_mock_client(self._LLM_RESPONSE)

        with patch("pyads.extractor.MISTRAL_API_KEY", "test-key"), \
                patch("pyads.extractor.Mistral", return_value=client):
            extractor.process_text_files(
                text_dir=text_dir,
                output_dir=output_dir,
                second_pass=True,
            )

        self.assertEqual(client.chat.complete.call_count, 2)

    def test_confidence_key_present_in_record(self):
        text_dir, output_dir = self._setup_dirs()
        client = _make_mock_client(self._LLM_RESPONSE)

        with patch("pyads.extractor.MISTRAL_API_KEY", "test-key"), \
                patch("pyads.extractor.Mistral", return_value=client):
            records, _, _ = extractor.process_text_files(
                text_dir=text_dir,
                output_dir=output_dir,
                second_pass=True,
            )

        self.assertIn("confidence", records[0])
        self.assertIn("overall", records[0]["confidence"])

    def test_raises_when_no_api_key(self):
        text_dir, output_dir = self._setup_dirs()

        with patch("pyads.extractor.MISTRAL_API_KEY", None):
            with self.assertRaises(RuntimeError):
                extractor.process_text_files(text_dir=text_dir, output_dir=output_dir)

    def test_raises_when_no_text_files(self):
        with tempfile.TemporaryDirectory() as empty_dir, \
                tempfile.TemporaryDirectory() as output_dir:
            with patch("pyads.extractor.MISTRAL_API_KEY", "test-key"):
                with self.assertRaises(FileNotFoundError):
                    extractor.process_text_files(
                        text_dir=empty_dir,
                        output_dir=output_dir,
                    )


class FlattenRecordTests(unittest.TestCase):
    """Tests for the public flatten_record helper."""

    def test_returns_flat_dict_with_expected_keys(self):
        record = extractor._empty_record("paper.txt")
        record["material"] = "ZIF-8"
        record["gases"] = ["CO2", "N2"]

        flat = extractor.flatten_record(record)

        self.assertIn("material", flat)
        self.assertIn("bet_surface_area_value", flat)
        self.assertIn("gases", flat)
        self.assertEqual(flat["material"], "ZIF-8")
        self.assertEqual(flat["gases"], "CO2; N2")

    def test_nested_surface_area_is_flattened(self):
        record = extractor._empty_record("paper.txt")
        record["surface_area"] = {"value": 1200.0, "unit": "m2/g"}

        flat = extractor.flatten_record(record)

        self.assertEqual(flat["bet_surface_area_value"], 1200.0)
        self.assertEqual(flat["bet_surface_area_unit"], "m2/g")

    def test_null_surface_area_flattens_to_none(self):
        record = extractor._empty_record("paper.txt")
        flat = extractor.flatten_record(record)

        self.assertIsNone(flat["bet_surface_area_value"])


if __name__ == "__main__":
    unittest.main()
