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
from pyads.extractor import _empty_material  # noqa: E402


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


def _make_paper(materials=None):
    """Return a minimal v2 paper dict for testing."""
    if materials is None:
        materials = []
    return {
        "schema_version": 2,
        "source_file": "test.txt",
        "doi": None,
        "title": None,
        "year": None,
        "materials": materials,
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
    """Tests for merging targeted extraction results into a material dict."""

    def _base(self):
        mat = _empty_material()
        mat["source_file"] = "test.txt"
        mat["pore_volume"] = {"value": 0.55, "unit": "cm3/g"}
        return mat

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
    """Integration tests for the full adaptive_extract loop (returns paper, usage)."""

    _HIGH_CONF_MAT = {
        "material": "ZIF-8",
        "surface_area": {"value": 1621.0, "unit": "m2/g"},
        "pore_volume": {"value": 0.636, "unit": "cm3/g"},
        "pore_size": {"value": None, "unit": None},
        "gases": ["CO2"],
        "isotherm_temperatures": [{"value": 298, "unit": "K"}],
    }

    def _high_conf_response(self):
        import json  # pylint: disable=import-outside-toplevel
        return json.dumps({
            "doi": None, "title": None, "year": None,
            "materials": [self._HIGH_CONF_MAT],
        })

    def test_returns_paper_and_usage_tuple(self):
        client = _make_client(self._high_conf_response())
        result = adaptive_extract("BET 1621 m2/g", "test.txt", client, "mistral-small-latest")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_paper_has_schema_version_2(self):
        client = _make_client(self._high_conf_response())
        paper, _ = adaptive_extract("BET 1621 m2/g", "test.txt", client, "mistral-small-latest")
        self.assertEqual(paper["schema_version"], 2)

    def test_material_extracted_correctly(self):
        client = _make_client(self._high_conf_response())
        paper, _ = adaptive_extract("BET 1621 m2/g", "test.txt", client, "mistral-small-latest")
        self.assertEqual(len(paper["materials"]), 1)
        self.assertEqual(paper["materials"][0]["material"], "ZIF-8")

    def test_confidence_embedded_per_material(self):
        client = _make_client(self._high_conf_response())
        paper, _ = adaptive_extract("BET 1621 m2/g", "test.txt", client, "mistral-small-latest")
        mat = paper["materials"][0]
        self.assertIn("confidence", mat)
        self.assertIn("overall", mat["confidence"])

    def test_usage_has_token_counts(self):
        client = _make_client(self._high_conf_response())
        _, usage = adaptive_extract("BET 1621 m2/g", "test.txt", client, "mistral-small-latest")
        self.assertIn("total_tokens", usage)

    def test_no_targeted_pass_when_all_fields_high_confidence(self):
        """When both passes agree, only 2 LLM calls should be made (no targeted pass)."""
        client = _make_client(self._high_conf_response())
        adaptive_extract("BET 1621 m2/g", "test.txt", client, "mistral-small-latest")
        self.assertEqual(client.chat.complete.call_count, 2)

    def test_targeted_pass_runs_when_surface_area_low(self):
        """When validation rejects surface_area, a third targeted call should fire."""
        import json  # pylint: disable=import-outside-toplevel

        first_mat = {
            "material": "ZIF-8",
            "surface_area": {"value": 0.636, "unit": "cm3/g"},  # wrong unit
            "pore_volume": {"value": 0.636, "unit": "cm3/g"},
            "pore_size": {"value": None, "unit": None},
            "gases": [], "isotherm_temperatures": [],
        }
        second_mat = {
            "material": "ZIF-8",
            "surface_area": {"value": None, "unit": None},  # rejected by validation
            "pore_volume": {"value": 0.636, "unit": "cm3/g"},
            "pore_size": {"value": None, "unit": None},
            "gases": [], "isotherm_temperatures": [],
        }
        first_paper = _make_paper(materials=[first_mat])
        second_paper = _make_paper(materials=[second_mat])
        targeted_result = {"surface_area": {"value": 1621.0, "unit": "m2/g"}}

        with patch("pyads.agent.extract_data_from_text") as mock_extract, \
             patch("pyads.agent.validate_record_from_text") as mock_validate, \
             patch("pyads.agent._chat_json_with_retries") as mock_targeted:

            mock_extract.return_value = (first_paper, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
            mock_validate.return_value = (second_paper, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
            mock_targeted.return_value = (targeted_result, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})

            paper, _ = adaptive_extract("text", "test.txt", MagicMock(), "mistral-small-latest")

        mock_targeted.assert_called_once()
        self.assertEqual(paper["materials"][0]["surface_area"]["value"], 1621.0)


if __name__ == "__main__":
    unittest.main()
