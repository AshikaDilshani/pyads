"""Unit tests for pyads.confidence — extraction confidence scoring."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads.confidence import compute_confidence, overall_confidence, score_fields  # noqa: E402


def _record(**kwargs) -> dict:
    """Build a minimal record with sane defaults."""
    base = {
        "doi": None,
        "title": None,
        "year": None,
        "material": None,
        "surface_area": {"value": None, "unit": None},
        "pore_volume": {"value": None, "unit": None},
        "pore_size": {"value": None, "unit": None},
        "gases": [],
        "isotherm_temperatures": [],
    }
    base.update(kwargs)
    return base


class ScoreFieldsTests(unittest.TestCase):
    """Tests for per-field confidence scoring."""

    def test_identical_records_score_high_on_extracted_fields(self):
        rec = _record(material="ZIF-8", year=2023)
        scores = score_fields(rec, rec)
        self.assertEqual(scores["material"], "high")
        self.assertEqual(scores["year"], "high")

    def test_both_null_scores_absent(self):
        rec = _record()
        scores = score_fields(rec, rec)
        self.assertEqual(scores["material"], "absent")
        self.assertEqual(scores["doi"], "absent")

    def test_second_pass_corrects_value_scores_low(self):
        r1 = _record(material="MOF")
        r2 = _record(material="ZIF-8")
        scores = score_fields(r1, r2)
        self.assertEqual(scores["material"], "low")

    def test_second_pass_adds_value_scores_medium(self):
        r1 = _record(material=None)
        r2 = _record(material="ZIF-8")
        scores = score_fields(r1, r2)
        self.assertEqual(scores["material"], "medium")

    def test_numeric_field_same_value_and_unit_scores_high(self):
        measure = {"value": 1200.0, "unit": "m2/g"}
        r1 = _record(surface_area=measure)
        r2 = _record(surface_area=measure)
        scores = score_fields(r1, r2)
        self.assertEqual(scores["surface_area"], "high")

    def test_numeric_field_unit_corrected_scores_low(self):
        r1 = _record(surface_area={"value": 0.5, "unit": "cm3/g"})
        r2 = _record(surface_area={"value": None, "unit": None})
        scores = score_fields(r1, r2)
        self.assertEqual(scores["surface_area"], "low")

    def test_gases_list_identical_scores_high(self):
        r1 = _record(gases=["CO2", "N2"])
        r2 = _record(gases=["CO2", "N2"])
        scores = score_fields(r1, r2)
        self.assertEqual(scores["gases"], "high")

    def test_gases_list_differs_scores_low(self):
        r1 = _record(gases=["CO2"])
        r2 = _record(gases=["CO2", "N2"])
        scores = score_fields(r1, r2)
        self.assertEqual(scores["gases"], "low")


class OverallConfidenceTests(unittest.TestCase):
    """Tests for the overall confidence aggregation."""

    def test_all_high_returns_high(self):
        self.assertEqual(overall_confidence({"a": "high", "b": "high"}), "high")

    def test_any_low_returns_low(self):
        self.assertEqual(overall_confidence({"a": "high", "b": "low"}), "low")

    def test_absent_fields_ignored(self):
        self.assertEqual(overall_confidence({"a": "high", "b": "absent"}), "high")

    def test_mix_without_low_returns_medium(self):
        self.assertEqual(overall_confidence({"a": "high", "b": "medium"}), "medium")

    def test_all_absent_returns_absent(self):
        self.assertEqual(overall_confidence({"a": "absent", "b": "absent"}), "absent")


class ComputeConfidenceTests(unittest.TestCase):
    """Integration tests for compute_confidence."""

    def test_returns_overall_and_fields_keys(self):
        rec = _record(material="ZIF-8")
        result = compute_confidence(rec, rec)
        self.assertIn("overall", result)
        self.assertIn("fields", result)

    def test_single_pass_all_high(self):
        rec = _record(material="ZIF-8", year=2023, gases=["CO2"])
        result = compute_confidence(rec, rec)
        self.assertEqual(result["overall"], "high")

    def test_unit_correction_causes_low_overall(self):
        r1 = _record(surface_area={"value": 0.55, "unit": "cm3/g"})
        r2 = _record(surface_area={"value": None, "unit": None})
        result = compute_confidence(r1, r2)
        self.assertEqual(result["overall"], "low")
        self.assertEqual(result["fields"]["surface_area"], "low")

    def test_empty_record_returns_absent(self):
        rec = _record()
        result = compute_confidence(rec, rec)
        self.assertEqual(result["overall"], "absent")


if __name__ == "__main__":
    unittest.main()
