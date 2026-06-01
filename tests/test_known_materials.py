"""Unit tests for pyads.known_materials — fully offline."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads.known_materials import (  # noqa: E402
    find_known_material,
    validate_known_material,
)


class FindKnownMaterialTests(unittest.TestCase):
    """Tests for alias-based material lookup."""

    def test_exact_canonical_name_matches(self):
        entry = find_known_material("ZIF-8")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["canonical_name"], "ZIF-8")

    def test_case_insensitive_match(self):
        entry = find_known_material("zif-8")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["canonical_name"], "ZIF-8")

    def test_alias_cu_btc_resolves_to_hkust1(self):
        entry = find_known_material("Cu-BTC")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["canonical_name"], "HKUST-1")

    def test_alias_irmof1_resolves_to_mof5(self):
        entry = find_known_material("IRMOF-1")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["canonical_name"], "MOF-5")

    def test_whitespace_insensitive_match(self):
        entry = find_known_material("MIL 101 Cr")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["canonical_name"], "MIL-101(Cr)")

    def test_unknown_material_returns_none(self):
        self.assertIsNone(find_known_material("UNKNOWN-MOF-XYZ"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(find_known_material(""))

    def test_aliases_key_not_in_returned_dict(self):
        entry = find_known_material("ZIF-8")
        self.assertNotIn("aliases", entry)

    def test_zeolite_13x_alias(self):
        entry = find_known_material("13X")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["canonical_name"], "Zeolite 13X")


class ValidateKnownMaterialTests(unittest.TestCase):
    """Tests for out-of-range detection against literature values."""

    def _record(self, sa=None, pv=None, ps=None, ps_unit="Å"):
        """Build a minimal extraction record."""
        return {
            "surface_area": {"value": sa, "unit": "m2/g"} if sa else {"value": None, "unit": None},
            "pore_volume": {"value": pv, "unit": "cm3/g"} if pv else {"value": None, "unit": None},
            "pore_size": {"value": ps, "unit": ps_unit} if ps else {"value": None, "unit": None},
        }

    def test_in_range_values_produce_no_warnings(self):
        record = self._record(sa=1600, pv=0.60, ps=3.4)
        warnings = validate_known_material("ZIF-8", record)
        self.assertEqual(warnings, [])

    def test_out_of_range_surface_area_warns(self):
        record = self._record(sa=50000)
        warnings = validate_known_material("ZIF-8", record)
        self.assertTrue(any("surface_area" in w for w in warnings))

    def test_out_of_range_pore_volume_warns(self):
        record = self._record(sa=1600, pv=5.0)
        warnings = validate_known_material("ZIF-8", record)
        self.assertTrue(any("pore_volume" in w for w in warnings))

    def test_null_values_are_skipped(self):
        record = self._record()
        warnings = validate_known_material("ZIF-8", record)
        self.assertEqual(warnings, [])

    def test_pore_size_in_nm_is_converted(self):
        # ZIF-8 pore size ~3.4 Å = 0.34 nm; 10 nm would be out-of-range
        record = self._record(ps=10.0, ps_unit="nm")
        warnings = validate_known_material("ZIF-8", record)
        self.assertTrue(any("pore_size" in w for w in warnings))

    def test_unknown_material_returns_no_warnings(self):
        record = self._record(sa=99999)
        warnings = validate_known_material("UNKNOWN-MOF-XYZ", record)
        self.assertEqual(warnings, [])

    def test_alias_is_resolved_before_validation(self):
        # Cu-BTC is HKUST-1; surface area 1500 m2/g is within its range.
        record = self._record(sa=1500, pv=0.80)
        warnings = validate_known_material("Cu-BTC", record)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
