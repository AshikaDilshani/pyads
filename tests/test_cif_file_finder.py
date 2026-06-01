"""Unit tests for pyads.cif_finder — offline, no network I/O."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads import cif_finder  # noqa: E402


class CifFinderTests(unittest.TestCase):
    """Tests for COD query building, deduplication, and result selection."""

    def test_unique_material_rows_uses_adsorption_columns(self):
        dataframe = pd.DataFrame(
            [
                {"material": "CALF-20", "doi": "10.1/example", "title": "Paper title"},
                {"material": "CALF-20", "doi": "10.1/example", "title": "Paper title"},
                {"material": "MOF", "doi": "10.2/generic", "title": "Generic material"},
            ]
        )

        rows = cif_finder.unique_material_rows(dataframe)

        self.assertEqual(rows, [{"material": "CALF-20", "doi": "10.1/example", "title": "Paper title"}])

    def test_candidate_queries_include_material_doi_and_title(self):
        queries = cif_finder.candidate_queries(
            "HKUST-1@PS_63",
            "10.1002_adma.201403827",
            "Protecting Metal-Organic Framework Crystals",
        )

        self.assertIn("HKUST-1@PS_63", queries)
        self.assertIn("HKUST-1@PS 63", queries)
        self.assertIn("10.1002/adma.201403827", queries)
        self.assertIn("Protecting Metal-Organic Framework Crystals", queries)

    def test_choose_best_cod_result_prefers_material_name(self):
        results = [
            {"file": "1", "title": "Unrelated compound"},
            {"file": "2", "title": "CALF-20 porous framework"},
        ]

        result = cif_finder.choose_best_cod_result(results, "CALF-20", "")

        self.assertEqual(result["file"], "2")

    def test_looks_like_cif_requires_cif_markers(self):
        self.assertTrue(cif_finder.looks_like_cif("data_test\n_cell_length_a 1\n"))
        self.assertFalse(cif_finder.looks_like_cif("plain text"))


class SafeFilenameTests(unittest.TestCase):
    """Tests for filesystem-safe material name conversion."""

    def test_replaces_forbidden_characters(self):
        name = cif_finder.safe_filename('ZIF-8: "porous" <MOF>')
        for char in (':', '"', '<', '>'):
            self.assertNotIn(char, name)

    def test_truncates_to_max_length(self):
        long_name = "A" * 200
        result = cif_finder.safe_filename(long_name, max_length=120)
        self.assertLessEqual(len(result), 120)

    def test_returns_unknown_material_for_empty_input(self):
        self.assertEqual(cif_finder.safe_filename(""), "unknown_material")

    def test_collapses_spaces_to_underscores(self):
        result = cif_finder.safe_filename("Zeolite 13X")
        self.assertIn("_", result)
        self.assertNotIn(" ", result)


class UsefulMaterialTests(unittest.TestCase):
    """Tests for the material-name usefulness filter."""

    def test_rejects_generic_mof(self):
        self.assertFalse(cif_finder.useful_material("MOF"))

    def test_rejects_name_shorter_than_three_chars(self):
        self.assertFalse(cif_finder.useful_material("ab"))

    def test_rejects_empty_string(self):
        self.assertFalse(cif_finder.useful_material(""))

    def test_accepts_specific_material_name(self):
        self.assertTrue(cif_finder.useful_material("ZIF-8"))
        self.assertTrue(cif_finder.useful_material("HKUST-1"))
        self.assertTrue(cif_finder.useful_material("MIL-101(Cr)"))

    def test_rejects_nan_string(self):
        self.assertFalse(cif_finder.useful_material("nan"))


class WriteReportTests(unittest.TestCase):
    """Tests for CIF download report CSV writing."""

    def test_creates_csv_with_expected_columns(self):
        rows = [
            cif_finder.make_report_row("ZIF-8", "downloaded", "ZIF-8", "1234567", "zif8.cif"),
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_path = Path(tmp_dir) / "report.csv"
            cif_finder.write_report(rows, report_path)

            self.assertTrue(report_path.exists())
            with report_path.open(encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                saved_rows = list(reader)

        self.assertEqual(len(saved_rows), 1)
        self.assertEqual(saved_rows[0]["material"], "ZIF-8")
        self.assertEqual(saved_rows[0]["status"], "downloaded")

    def test_overwrites_existing_report(self):
        rows_first = [cif_finder.make_report_row("ZIF-8", "downloaded", "q")]
        rows_second = [cif_finder.make_report_row("HKUST-1", "not_found", "q")]

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "report.csv"
            cif_finder.write_report(rows_first, path)
            cif_finder.write_report(rows_second, path)

            with path.open(encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                saved_rows = list(reader)

        self.assertEqual(len(saved_rows), 1)
        self.assertEqual(saved_rows[0]["material"], "HKUST-1")


class CandidateQueriesEdgeCasesTests(unittest.TestCase):
    """Edge-case tests for COD query construction."""

    def test_deduplicates_identical_queries(self):
        queries = cif_finder.candidate_queries("ZIF-8", "", "")
        self.assertEqual(len(queries), len(set(q.lower() for q in queries)))

    def test_skips_empty_doi(self):
        queries = cif_finder.candidate_queries("ZIF-8", "", "")
        self.assertNotIn("", queries)

    def test_skips_not_found_doi(self):
        queries = cif_finder.candidate_queries("ZIF-8", "not_found", "")
        self.assertEqual(queries, ["ZIF-8"])

    def test_includes_title_when_long_enough(self):
        title = "A study of CO2 adsorption in ZIF-8 at 298 K"
        queries = cif_finder.candidate_queries("ZIF-8", "", title)
        self.assertTrue(any(title[:20] in q for q in queries))

    def test_skips_short_title(self):
        queries = cif_finder.candidate_queries("ZIF-8", "", "Short")
        self.assertNotIn("Short", queries)


if __name__ == "__main__":
    unittest.main()
