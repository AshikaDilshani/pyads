"""Unit tests for pyads.benchmark — offline evaluation against ground truth."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads import benchmark  # noqa: E402


def _gt_paper(doi="10.1/test", materials=None):
    if materials is None:
        materials = [_gt_material()]
    return {"doi": doi, "materials": materials}


def _gt_material(
    material="ZIF-8",
    sa=1630.0, pv=0.636, ps=11.6,
    gases=None,
):
    return {
        "material": material,
        "surface_area": {"value": sa, "unit": "m2/g"},
        "pore_volume": {"value": pv, "unit": "cm3/g"},
        "pore_size": {"value": ps, "unit": "A"},
        "gases": gases if gases is not None else ["N2"],
    }


def _ext_paper(doi="10.1/test", materials=None):
    if materials is None:
        materials = [_ext_material()]
    return {
        "schema_version": 2,
        "source_file": "paper.txt",
        "doi": doi,
        "title": "Test paper",
        "year": 2024,
        "materials": materials,
    }


def _ext_material(
    material="ZIF-8",
    sa=1630.0, pv=0.636, ps=11.6,
    gases=None,
):
    return {
        "material": material,
        "surface_area": {"value": sa, "unit": "m2/g"},
        "pore_volume": {"value": pv, "unit": "cm3/g"},
        "pore_size": {"value": ps, "unit": "A"},
        "gases": gases if gases is not None else ["N2"],
        "isotherm_temperatures": [],
    }


class WithinToleranceTests(unittest.TestCase):
    """Tests for the numeric tolerance helper."""

    def test_exact_match(self):
        self.assertTrue(benchmark._within_tolerance(1000, 1000, 0.05))

    def test_within_5_percent(self):
        self.assertTrue(benchmark._within_tolerance(1050, 1000, 0.05))

    def test_just_outside_tolerance(self):
        self.assertFalse(benchmark._within_tolerance(1060, 1000, 0.05))

    def test_none_extracted_returns_false(self):
        self.assertFalse(benchmark._within_tolerance(None, 1000, 0.05))

    def test_none_truth_returns_false(self):
        self.assertFalse(benchmark._within_tolerance(1000, None, 0.05))

    def test_zero_truth_exact_zero_extracted(self):
        self.assertTrue(benchmark._within_tolerance(0, 0, 0.05))


class FindMatchingMaterialTests(unittest.TestCase):
    """Tests for material name matching."""

    def _materials(self):
        return [
            {"material": "ZIF-8", "surface_area": {"value": 1630, "unit": "m2/g"}},
            {"material": "HKUST-1", "surface_area": {"value": 1507, "unit": "m2/g"}},
        ]

    def test_exact_match(self):
        result = benchmark._find_matching_material(self._materials(), "ZIF-8")
        self.assertIsNotNone(result)
        self.assertEqual(result["material"], "ZIF-8")

    def test_case_insensitive_match(self):
        result = benchmark._find_matching_material(self._materials(), "zif-8")
        self.assertIsNotNone(result)
        self.assertEqual(result["material"], "ZIF-8")

    def test_substring_fallback(self):
        result = benchmark._find_matching_material(self._materials(), "HKUST")
        self.assertIsNotNone(result)
        self.assertEqual(result["material"], "HKUST-1")

    def test_no_match_returns_none(self):
        result = benchmark._find_matching_material(self._materials(), "MOF-177")
        self.assertIsNone(result)

    def test_empty_list_returns_none(self):
        result = benchmark._find_matching_material([], "ZIF-8")
        self.assertIsNone(result)


class EvaluateMaterialTests(unittest.TestCase):
    """Tests for per-material field scoring."""

    def test_perfect_match_all_correct(self):
        gt = _gt_material()
        ext = _ext_material()
        scores = benchmark.evaluate_material(ext, gt)
        for field in ("surface_area", "pore_volume", "pore_size", "material", "gases"):
            self.assertEqual(scores[field], "correct", f"{field} should be correct")

    def test_none_extracted_all_missing(self):
        scores = benchmark.evaluate_material(None, _gt_material())
        for field in ("surface_area", "pore_volume", "pore_size", "material", "gases"):
            self.assertEqual(scores[field], "missing")

    def test_surface_area_within_tolerance_is_correct(self):
        ext = _ext_material(sa=1650.0)  # 1.2% off
        scores = benchmark.evaluate_material(ext, _gt_material(sa=1630.0))
        self.assertEqual(scores["surface_area"], "correct")

    def test_surface_area_outside_tolerance_is_wrong(self):
        ext = _ext_material(sa=500.0)
        scores = benchmark.evaluate_material(ext, _gt_material(sa=1630.0))
        self.assertEqual(scores["surface_area"], "wrong")

    def test_missing_surface_area_is_missing(self):
        ext = _ext_material()
        ext["surface_area"] = {"value": None, "unit": None}
        scores = benchmark.evaluate_material(ext, _gt_material())
        self.assertEqual(scores["surface_area"], "missing")

    def test_null_ground_truth_field_extra_when_extracted(self):
        gt = _gt_material(ps=None)
        gt["pore_size"] = None
        ext = _ext_material(ps=3.4)
        scores = benchmark.evaluate_material(ext, gt)
        self.assertEqual(scores["pore_size"], "extra")

    def test_null_ground_truth_null_extracted_is_correct(self):
        gt = _gt_material()
        gt["pore_size"] = None
        ext = _ext_material()
        ext["pore_size"] = {"value": None, "unit": None}
        scores = benchmark.evaluate_material(ext, gt)
        self.assertEqual(scores["pore_size"], "correct")

    def test_wrong_material_name_is_wrong(self):
        ext = _ext_material(material="MOF-5")
        scores = benchmark.evaluate_material(ext, _gt_material(material="ZIF-8"))
        self.assertEqual(scores["material"], "wrong")

    def test_partial_gases_match_is_partial(self):
        ext = _ext_material(gases=["N2"])
        scores = benchmark.evaluate_material(ext, _gt_material(gases=["N2", "CO2"]))
        self.assertEqual(scores["gases"], "partial")

    def test_no_gas_overlap_is_wrong(self):
        ext = _ext_material(gases=["CO2"])
        scores = benchmark.evaluate_material(ext, _gt_material(gases=["N2"]))
        self.assertEqual(scores["gases"], "wrong")

    def test_missing_gases_when_gt_has_gases(self):
        ext = _ext_material(gases=[])
        scores = benchmark.evaluate_material(ext, _gt_material(gases=["N2"]))
        self.assertEqual(scores["gases"], "missing")


class AggregateScoresTests(unittest.TestCase):
    """Tests for precision/recall/F1 aggregation."""

    def test_all_correct_gives_f1_one(self):
        scores = [{"surface_area": "correct", "pore_volume": "correct",
                   "pore_size": "correct", "material": "correct", "gases": "correct"}]
        metrics = benchmark.aggregate_scores(scores)
        for field in ("surface_area", "pore_volume", "material"):
            self.assertAlmostEqual(metrics[field]["f1"], 1.0)

    def test_all_missing_gives_f1_zero(self):
        scores = [{"surface_area": "missing", "pore_volume": "missing",
                   "pore_size": "missing", "material": "missing", "gases": "missing"}]
        metrics = benchmark.aggregate_scores(scores)
        self.assertEqual(metrics["surface_area"]["f1"], 0.0)

    def test_mixed_correct_and_wrong(self):
        scores = [
            {"surface_area": "correct", "pore_volume": "correct",
             "pore_size": "correct", "material": "correct", "gases": "correct"},
            {"surface_area": "wrong", "pore_volume": "correct",
             "pore_size": "missing", "material": "correct", "gases": "correct"},
        ]
        metrics = benchmark.aggregate_scores(scores)
        self.assertLess(metrics["surface_area"]["f1"], 1.0)
        self.assertAlmostEqual(metrics["pore_volume"]["f1"], 1.0)


class RunEvaluationTests(unittest.TestCase):
    """End-to-end tests for run_evaluation using temp files."""

    def _write_json(self, path, data):
        Path(path).write_text(json.dumps(data), encoding="utf-8")

    def test_perfect_extraction_all_fields_f1_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext_path = Path(tmp) / "extracted.json"
            gt_path = Path(tmp) / "ground_truth.json"
            self._write_json(ext_path, [_ext_paper()])
            self._write_json(gt_path, {"version": 1, "papers": [_gt_paper()]})

            report = benchmark.run_evaluation(ext_path, gt_path)

        self.assertEqual(report["papers_evaluated"], 1)
        self.assertEqual(report["materials_evaluated"], 1)
        for field in ("surface_area", "pore_volume", "material"):
            self.assertAlmostEqual(report["field_metrics"][field]["f1"], 1.0)

    def test_unmatched_doi_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext_path = Path(tmp) / "extracted.json"
            gt_path = Path(tmp) / "ground_truth.json"
            self._write_json(ext_path, [_ext_paper(doi="10.1/other")])
            self._write_json(gt_path, {"version": 1, "papers": [_gt_paper(doi="10.1/test")]})

            report = benchmark.run_evaluation(ext_path, gt_path)

        self.assertIn("10.1/test", report["unmatched_papers"])

    def test_multiple_papers_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext_path = Path(tmp) / "extracted.json"
            gt_path = Path(tmp) / "ground_truth.json"
            self._write_json(ext_path, [
                _ext_paper(doi="10.1/a"),
                _ext_paper(doi="10.1/b", materials=[_ext_material(material="HKUST-1")]),
            ])
            self._write_json(gt_path, {"version": 1, "papers": [
                _gt_paper(doi="10.1/a"),
                _gt_paper(doi="10.1/b", materials=[_gt_material(material="HKUST-1")]),
            ]})

            report = benchmark.run_evaluation(ext_path, gt_path)

        self.assertEqual(report["papers_evaluated"], 2)
        self.assertEqual(report["materials_evaluated"], 2)

    def test_wrong_surface_area_reduces_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            ext_path = Path(tmp) / "extracted.json"
            gt_path = Path(tmp) / "ground_truth.json"
            self._write_json(ext_path, [_ext_paper(
                materials=[_ext_material(sa=500.0)]  # wrong value
            )])
            self._write_json(gt_path, {"version": 1, "papers": [_gt_paper()]})

            report = benchmark.run_evaluation(ext_path, gt_path)

        self.assertLess(report["field_metrics"]["surface_area"]["recall"], 1.0)

    def test_real_ground_truth_file_is_loadable(self):
        """Verify the shipped ground_truth.json parses without error."""
        gt_path = (
            Path(__file__).resolve().parents[1] / "data" / "benchmark" / "ground_truth.json"
        )
        self.assertTrue(gt_path.exists(), "data/benchmark/ground_truth.json not found")
        data = json.loads(gt_path.read_text(encoding="utf-8"))
        self.assertIn("papers", data)
        self.assertGreaterEqual(len(data["papers"]), 3)


if __name__ == "__main__":
    unittest.main()
