"""Unit tests for pyads.extractor — offline, Mistral client is fully mocked."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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


if __name__ == "__main__":
    unittest.main()
