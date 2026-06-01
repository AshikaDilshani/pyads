"""Literature-sourced property ranges for common porous materials.

This module provides a lookup table of expected BET surface area, pore volume,
and pore size ranges for well-characterised MOFs, COFs, and zeolites.  It is
used by the agentic extraction loop to catch cases where the two LLM passes
*agree* on a physically implausible value — a situation that per-field
confidence scoring cannot detect on its own.

Usage
-----
    from pyads.known_materials import find_known_material, validate_known_material

    entry = find_known_material("Cu-BTC")
    if entry:
        warnings = validate_known_material("Cu-BTC", record)
        # warnings is a list of human-readable strings, empty when all in range.

Property ranges
---------------
Ranges are intentionally wide (literature values vary with activation
conditions, solvent, and measurement protocol).  They are used only to flag
*gross* outliers — values that differ from consensus by more than a factor of
two or three.  A warning does not mean the extracted value is wrong; it means
a human should verify.

All surface areas are in m²/g, pore volumes in cm³/g, pore sizes in Å.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Lookup table — (lo, hi) inclusive ranges for each property.
# ---------------------------------------------------------------------------

KNOWN_MATERIAL_PROPERTIES: dict[str, dict[str, Any]] = {
    "ZIF-8": {
        "surface_area_m2g": (1200, 1900),
        "pore_volume_cm3g": (0.45, 0.75),
        "pore_size_A": (2.5, 4.5),
        "aliases": ["zif8", "zif 8", "zinc imidazolate framework 8", "zn(mim)2"],
    },
    "HKUST-1": {
        "surface_area_m2g": (1200, 2200),
        "pore_volume_cm3g": (0.65, 1.10),
        "pore_size_A": (7.0, 12.0),
        "aliases": [
            "cu-btc", "cubtc", "cu btc", "hkust1", "hkust 1",
            "mof-199", "mof199", "basolite c300",
        ],
    },
    "MOF-5": {
        "surface_area_m2g": (2800, 4500),
        "pore_volume_cm3g": (0.9, 1.6),
        "pore_size_A": (7.0, 16.0),
        "aliases": [
            "irmof-1", "irmof1", "irmof 1", "mof5", "mof 5",
            "zn4o(bdc)3", "isoreticular mof",
        ],
    },
    "UiO-66": {
        "surface_area_m2g": (900, 1600),
        "pore_volume_cm3g": (0.35, 0.65),
        "pore_size_A": (5.0, 9.0),
        "aliases": ["uio66", "uio 66", "zr-mof", "uio-66-h2"],
    },
    "MIL-53(Al)": {
        "surface_area_m2g": (900, 1600),
        "pore_volume_cm3g": (0.45, 0.85),
        "pore_size_A": (6.0, 12.0),
        "aliases": [
            "mil53al", "mil 53 al", "mil-53 al", "al-mil-53",
            "aluminium terephthalate",
        ],
    },
    "MIL-100(Fe)": {
        "surface_area_m2g": (1500, 2400),
        "pore_volume_cm3g": (0.75, 1.30),
        "pore_size_A": (15.0, 30.0),
        "aliases": ["mil100fe", "mil 100 fe", "mil-100 fe", "fe-mil-100"],
    },
    "MIL-101(Cr)": {
        "surface_area_m2g": (2500, 4200),
        "pore_volume_cm3g": (1.3, 2.4),
        "pore_size_A": (12.0, 35.0),
        "aliases": ["mil101cr", "mil 101 cr", "mil-101 cr", "cr-mil-101"],
    },
    "CALF-20": {
        "surface_area_m2g": (300, 700),
        "pore_volume_cm3g": (0.20, 0.55),
        "pore_size_A": (3.0, 7.0),
        "aliases": ["calf20", "calf 20", "zn-triazole", "canmet"],
    },
    "NU-1000": {
        "surface_area_m2g": (2000, 3200),
        "pore_volume_cm3g": (0.85, 1.60),
        "pore_size_A": (12.0, 35.0),
        "aliases": ["nu1000", "nu 1000"],
    },
    "MOF-177": {
        "surface_area_m2g": (3800, 5500),
        "pore_volume_cm3g": (1.4, 2.2),
        "pore_size_A": (10.0, 20.0),
        "aliases": ["mof177", "mof 177"],
    },
    "Zeolite 13X": {
        "surface_area_m2g": (450, 950),
        "pore_volume_cm3g": (0.25, 0.55),
        "pore_size_A": (7.0, 11.0),
        "aliases": ["13x", "zeolite13x", "nax", "faujasite", "13-x"],
    },
    "Mg-MOF-74": {
        "surface_area_m2g": (900, 1800),
        "pore_volume_cm3g": (0.45, 0.85),
        "pore_size_A": (9.0, 14.0),
        "aliases": [
            "mg mof 74", "mgmof74", "cpm-5", "mg-dobdc",
            "mg2(dobdc)", "mg-dobdc mof",
        ],
    },
    "ZIF-67": {
        "surface_area_m2g": (1300, 2000),
        "pore_volume_cm3g": (0.45, 0.75),
        "pore_size_A": (2.5, 4.5),
        "aliases": ["zif67", "zif 67", "cobalt imidazolate framework 67"],
    },
    "PCN-14": {
        "surface_area_m2g": (1500, 2400),
        "pore_volume_cm3g": (0.70, 1.20),
        "pore_size_A": (7.0, 14.0),
        "aliases": ["pcn14", "pcn 14"],
    },
    "DUT-49": {
        "surface_area_m2g": (4500, 7800),
        "pore_volume_cm3g": (1.8, 3.5),
        "pore_size_A": (14.0, 35.0),
        "aliases": ["dut49", "dut 49"],
    },
    "UiO-67": {
        "surface_area_m2g": (1800, 3200),
        "pore_volume_cm3g": (0.70, 1.30),
        "pore_size_A": (8.0, 14.0),
        "aliases": ["uio67", "uio 67", "uio-67-bpdc"],
    },
    "IRMOF-3": {
        "surface_area_m2g": (2000, 3500),
        "pore_volume_cm3g": (0.9, 1.5),
        "pore_size_A": (7.0, 16.0),
        "aliases": ["irmof3", "irmof 3", "zn4o(abdc)3"],
    },
    "Zeolite 4A": {
        "surface_area_m2g": (300, 700),
        "pore_volume_cm3g": (0.15, 0.40),
        "pore_size_A": (3.5, 5.0),
        "aliases": ["4a", "zeolite4a", "naa", "linde type a"],
    },
    "MIL-53(Fe)": {
        "surface_area_m2g": (750, 1400),
        "pore_volume_cm3g": (0.40, 0.80),
        "pore_size_A": (5.0, 10.0),
        "aliases": ["mil53fe", "mil 53 fe", "mil-53 fe", "fe-mil-53"],
    },
    "NU-110": {
        "surface_area_m2g": (5000, 8000),
        "pore_volume_cm3g": (2.4, 4.4),
        "pore_size_A": (10.0, 30.0),
        "aliases": ["nu110", "nu 110"],
    },
}


def _normalise_name(name: str) -> str:
    """Lowercase, strip spaces, hyphens, and underscores for fuzzy matching."""
    return re.sub(r"[\s\-_]", "", name.lower())


def find_known_material(material_name: str) -> dict[str, Any] | None:
    """Return the known-properties entry for *material_name*, or None.

    Matching is case-insensitive and tolerates spaces, hyphens, and
    underscores.  Returns a copy of the entry dict (without the alias list)
    plus an ``"canonical_name"`` key.
    """
    if not material_name or not material_name.strip():
        return None

    needle = _normalise_name(material_name)

    for canonical, entry in KNOWN_MATERIAL_PROPERTIES.items():
        # Direct name match.
        if needle == _normalise_name(canonical):
            return {**{k: v for k, v in entry.items() if k != "aliases"},
                    "canonical_name": canonical}

        # Alias match.
        for alias in entry.get("aliases", []):
            if needle == _normalise_name(alias):
                return {**{k: v for k, v in entry.items() if k != "aliases"},
                        "canonical_name": canonical}

    return None


def _unit_to_angstrom(value: float, unit: str) -> float | None:
    """Convert a pore-size measurement to Å for range comparison."""
    unit_norm = unit.lower().replace(" ", "")
    if unit_norm in ("a", "å", "angstrom", "angstroms"):
        return value
    if unit_norm == "nm":
        return value * 10.0
    return None  # Unknown unit — cannot compare.


def validate_known_material(
    material_name: str,
    record: dict[str, Any],
) -> list[str]:
    """Return a list of out-of-range warning strings for the extracted record.

    Compares ``surface_area``, ``pore_volume``, and ``pore_size`` against
    the known literature ranges for *material_name*.  Returns an empty list
    when all present values are within range or the material is unknown.

    Each warning is a human-readable string describing the discrepancy,
    suitable for logging or display.
    """
    entry = find_known_material(material_name)
    if entry is None:
        return []

    canonical = entry["canonical_name"]
    warnings: list[str] = []

    # Surface area check (m²/g).
    sa = record.get("surface_area") or {}
    sa_val = sa.get("value")
    if sa_val is not None:
        lo, hi = entry["surface_area_m2g"]
        if not lo <= sa_val <= hi:
            warnings.append(
                f"surface_area {sa_val} m²/g is outside the expected range "
                f"[{lo}–{hi}] m²/g for {canonical}."
            )

    # Pore volume check (cm³/g).
    pv = record.get("pore_volume") or {}
    pv_val = pv.get("value")
    if pv_val is not None:
        lo, hi = entry["pore_volume_cm3g"]
        if not lo <= pv_val <= hi:
            warnings.append(
                f"pore_volume {pv_val} cm³/g is outside the expected range "
                f"[{lo}–{hi}] cm³/g for {canonical}."
            )

    # Pore size check (convert to Å).
    ps = record.get("pore_size") or {}
    ps_val = ps.get("value")
    ps_unit = ps.get("unit") or ""
    if ps_val is not None and "pore_size_A" in entry:
        ps_angstrom = _unit_to_angstrom(ps_val, ps_unit)
        if ps_angstrom is not None:
            lo, hi = entry["pore_size_A"]
            if not lo <= ps_angstrom <= hi:
                warnings.append(
                    f"pore_size {ps_val} {ps_unit} ({ps_angstrom:.1f} Å) is "
                    f"outside the expected range [{lo}–{hi}] Å for {canonical}."
                )

    return warnings
