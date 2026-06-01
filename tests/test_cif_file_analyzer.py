"""Unit tests for pyads.cif_analyzer — offline, no network or file-system I/O."""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads import cif_analyzer  # noqa: E402


class CifAnalyzerTests(unittest.TestCase):
    """Tests for CIF metadata parsing and material-match scoring."""

    def test_common_name_is_used_when_systematic_name_is_placeholder(self):
        cif_text = """
data_calf-20
_chemical_name_systematic        ?
_chemical_name_common            CALF-20
_chemical_formula_sum            'C14 H8 N12 O9 Zn4'
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            cif_path = Path(temp_dir) / "CALF-20 CIF.cif"
            cif_path.write_text(cif_text, encoding="utf-8")
            metadata = cif_analyzer.cif_text_metadata(cif_path)

        self.assertEqual(metadata["chemical_name"], "CALF-20")
        self.assertEqual(metadata["chemical_formula"], "C14 H8 N12 O9 Zn4")

    def test_material_match_accepts_common_name(self):
        result = cif_analyzer.material_match_score(
            "CALF-20 CIF",
            {"chemical_name": "CALF-20", "chemical_formula": "", "publication_title": ""},
            "Zn4H8C14N12O9",
        )

        self.assertEqual(result["match_label"], "likely_match")
        self.assertEqual(result["match_score"], 1.0)

    def test_material_match_accepts_data_block_name(self):
        result = cif_analyzer.material_match_score(
            "CALF-20 CIF",
            {
                "chemical_name": "",
                "chemical_formula": "",
                "publication_title": "",
                "data_block": "calf-20",
                "file_stem": "CALF-20",
            },
            "Zn4H8C14N12O9",
        )

        self.assertEqual(result["match_label"], "likely_match")

    def test_material_match_does_not_accept_formula_only_wrong_material(self):
        result = cif_analyzer.material_match_score(
            "MIL-53(Al)",
            {"chemical_name": "?", "chemical_formula": "C2 H3 Al F5 N3 Zn", "publication_title": ""},
            "AlZnH3C2N3F5",
        )

        self.assertEqual(result["match_label"], "likely_wrong_material")

    def test_generic_material_is_rejected(self):
        result = cif_analyzer.material_match_score(
            "MOF",
            {"chemical_name": "CALF-20", "chemical_formula": "", "publication_title": ""},
            "Zn4H8C14N12O9",
        )

        self.assertEqual(result["match_label"], "reject_generic_material_name")


class NormalizeAndTokenTests(unittest.TestCase):
    """Tests for text-normalisation and tokenisation helpers."""

    def test_normalize_text_lowercases_and_strips(self):
        # Hyphens are replaced with spaces by normalize_text.
        result = cif_analyzer.normalize_text("  ZIF-8  ")
        self.assertEqual(result, "zif 8")

    def test_normalize_text_collapses_whitespace(self):
        result = cif_analyzer.normalize_text("MIL  101  Cr")
        self.assertNotIn("  ", result)

    def test_tokens_returns_meaningful_words(self):
        # "material" is in STOP_TOKENS and is excluded; "porous" and "zif" remain.
        result = cif_analyzer.tokens("ZIF-8 porous framework")
        self.assertIn("zif", result)
        self.assertIn("porous", result)

    def test_tokens_excludes_short_words(self):
        # Single-character tokens are noise — the function should skip them.
        result = cif_analyzer.tokens("a b c ZIF")
        for tok in result:
            self.assertGreater(len(tok), 1)


class SafeFloatTests(unittest.TestCase):
    """Tests for safe_float parsing."""

    def test_parses_valid_float_string(self):
        self.assertAlmostEqual(cif_analyzer.safe_float("3.14"), 3.14)

    def test_returns_none_for_non_numeric(self):
        self.assertIsNone(cif_analyzer.safe_float("?"))

    def test_returns_none_for_empty_string(self):
        self.assertIsNone(cif_analyzer.safe_float(""))

    def test_parses_integer_string(self):
        self.assertEqual(cif_analyzer.safe_float("42"), 42.0)


class MakeErrorRowTests(unittest.TestCase):
    """Tests for make_error_row output structure."""

    def test_error_row_has_all_expected_keys(self):
        row = cif_analyzer.make_error_row(
            {"material": "ZIF-8", "source": "doi:10.0/x", "identifier": "1234567"},
            Path("bad.cif"),
            "parse failed",
        )
        self.assertIn("material", row)
        self.assertIn("cif_file", row)
        self.assertIn("notes", row)
        self.assertEqual(row["material"], "ZIF-8")
        self.assertEqual(row["notes"], "parse failed")

    def test_error_row_cell_fields_are_empty(self):
        row = cif_analyzer.make_error_row(
            {"material": "ZIF-8", "source": "", "identifier": ""},
            Path("bad.cif"),
            "error",
        )
        # Cell parameter cells should be empty strings, not None or 0.
        for key in ("cell_a", "cell_b", "cell_c", "cell_alpha", "cell_beta", "cell_gamma"):
            self.assertEqual(row.get(key, ""), "")


class CifTextMetadataTests(unittest.TestCase):
    """Additional tests for CIF metadata extraction edge cases."""

    def test_publication_title_is_extracted(self):
        cif_text = (
            "data_test\n"
            "_publ_section_title 'Gas adsorption in ZIF-8'\n"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            cif_path = Path(tmp_dir) / "test.cif"
            cif_path.write_text(cif_text, encoding="utf-8")
            metadata = cif_analyzer.cif_text_metadata(cif_path)
        self.assertIn("ZIF-8", metadata.get("publication_title", ""))

    def test_missing_fields_default_to_empty_string(self):
        cif_text = "data_minimal\n_cell_length_a 10.0\n"
        with tempfile.TemporaryDirectory() as tmp_dir:
            cif_path = Path(tmp_dir) / "minimal.cif"
            cif_path.write_text(cif_text, encoding="utf-8")
            metadata = cif_analyzer.cif_text_metadata(cif_path)
        self.assertEqual(metadata.get("chemical_name", ""), "")


if __name__ == "__main__":
    unittest.main()
