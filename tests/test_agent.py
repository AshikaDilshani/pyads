"""Unit tests for pyads.agent — adaptive agentic extraction loop."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads.agent import (  # noqa: E402
    _apply_targeted,
    _low_confidence_numeric_fields,
    adaptive_extract,
)


def _make_client(response_json: str) -> MagicMock:
    """Build a Mistral client mock returning response_json."""
    msg = MagicMock()
    msg.content = response_json
    choice = MagicMock()
    choice.message = msg
    usage = MagicMock()
    usage.model_dump.return_value = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    client = MagicMock()
    client.chat.complete.return_value = response
    return client


def _confidence(surface_area="high", pore_volume="high", pore_size="absent"):
    return {
        "overall": "high",
        "fields": {
            "doi": "absent",
            "title": "absent",
            "year": "absent",
            "material": "absent",
            "surface_area": surface_area,
            "pore_volume": pore_volume,
            "pore_size": pore_size,
            "gases": "absent",
            "isotherm_temperatures": "absent",
        },
    }


class LowConfidenceFieldsTests(unittest.TestCase):
    """Tests for identifying which numeric fields need a targeted retry."""

    def test_returns_low_numeric_fields_only(self):
        conf = _confidence(surface_area="low", pore_volume="high")
        self.assertEqual(_low_confidence_numeric_fields(conf), ["surface_area"])

    def test_returns_empty_when_all_high(self):
        conf = _confidence(surface_area="high", pore_volume="high")
        self.assertEqual(_low_confidence_numeric_fields(conf), [])

    def test_returns_multiple_low_fields(self):
        conf = _confidence(surface_area="low", pore_volume="low", pore_size="low")
        result = _low_confidence_numeric_fields(conf)
        self.assertIn("surface_area", result)
        self.assertIn("pore_volume", result)
        self.assertIn("pore_size", result)


class ApplyTargetedTests(unittest.TestCase):
    """Tests for merging targeted extraction results into the base record."""

    def _base(self):
        return {
            "source_file": "test.txt",
            "schema_version": 1,
            "surface_area": {"value": None, "unit": None},
            "pore_volume": {"value": 0.55, "unit": "cm3/g"},
            "pore_size": {"value": None, "unit": None},
        }

    def test_valid_surface_area_is_merged(self):
        base = self._base()
        targeted = {"surface_area": {"value": 1621.0, "unit": "m2/g"}}
        result = _apply_targeted(base, targeted, ["surface_area"], "test.txt")
        self.assertEqual(result["surface_area"]["value"], 1621.0)

    def test_wrong_unit_is_not_merged(self):
        base = self._base()
        targeted = {"surface_area": {"value": 0.5, "unit": "cm3/g"}}
        result = _apply_targeted(base, targeted, ["surface_area"], "test.txt")
        self.assertIsNone(result["surface_area"]["value"])

    def test_existing_field_not_in_low_list_is_unchanged(self):
        base = self._base()
        targeted = {"pore_volume": {"value": 9.99, "unit": "cm3/g"}}
        result = _apply_targeted(base, targeted, ["surface_area"], "test.txt")
        self.assertEqual(result["pore_volume"]["value"], 0.55)


class AdaptiveExtractTests(unittest.TestCase):
    """Integration tests for the full adaptive_extract loop."""

    _HIGH_CONF_RESPONSE = (
        '{"doi": null, "title": null, "year": null, "material": "ZIF-8",'
        ' "surface_area": {"value": 1621.0, "unit": "m2/g"},'
        ' "pore_volume": {"value": 0.636, "unit": "cm3/g"},'
        ' "pore_size": {"value": null, "unit": null},'
        ' "gases": ["CO2"], "isotherm_temperatures": [{"value": 298, "unit": "K"}]}'
    )

    def test_no_targeted_pass_when_confidence_is_high(self):
        client = _make_client(self._HIGH_CONF_RESPONSE)
        record, conf, usage = adaptive_extract(
            "BET 1621 m2/g", "test.txt", client, "mistral-small-latest"
        )
        self.assertEqual(conf["overall"], "high")
        self.assertEqual(record["material"], "ZIF-8")
        self.assertIn("total_tokens", usage)

    def test_targeted_pass_runs_when_surface_area_low(self):
        low_conf_response = (
            '{"doi": null, "title": null, "year": null, "material": "ZIF-8",'
            ' "surface_area": {"value": 0.636, "unit": "cm3/g"},'
            ' "pore_volume": {"value": 0.636, "unit": "cm3/g"},'
            ' "pore_size": {"value": null, "unit": null},'
            ' "gases": [], "isotherm_temperatures": []}'
        )
        targeted_response = '{"surface_area": {"value": 1621.0, "unit": "m2/g"}}'

        # patch extract_data_from_text and validate_record_from_text to return
        # a low-confidence record, then check the targeted LLM call fires.
        with patch("pyads.agent.extract_data_from_text") as mock_extract, \
             patch("pyads.agent.validate_record_from_text") as mock_validate, \
             patch("pyads.agent._chat_json_with_retries") as mock_targeted:

            # First pass: wrong unit for surface_area
            first_record = {
                "schema_version": 1, "source_file": "test.txt",
                "material": "ZIF-8",
                "surface_area": {"value": 0.636, "unit": "cm3/g"},
                "pore_volume": {"value": 0.636, "unit": "cm3/g"},
                "pore_size": {"value": None, "unit": None},
                "doi": None, "title": None, "year": None,
                "gases": [], "isotherm_temperatures": [],
            }
            # Validation pass: surface_area rejected (wrong unit → null)
            second_record = {
                "schema_version": 1, "source_file": "test.txt",
                "material": "ZIF-8",
                "surface_area": {"value": None, "unit": None},
                "pore_volume": {"value": 0.636, "unit": "cm3/g"},
                "pore_size": {"value": None, "unit": None},
                "doi": None, "title": None, "year": None,
                "gases": [], "isotherm_temperatures": [],
            }
            mock_extract.return_value = (first_record, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
            mock_validate.return_value = (second_record, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
            mock_targeted.return_value = (
                {"surface_area": {"value": 1621.0, "unit": "m2/g"}},
                {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

            client = MagicMock()
            record, conf, _ = adaptive_extract("text", "test.txt", client, "mistral-small-latest")
            mock_targeted.assert_called_once()
            self.assertEqual(record["surface_area"]["value"], 1621.0)


if __name__ == "__main__":
    unittest.main()
