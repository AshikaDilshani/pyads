"""Shared constants and helpers used across the pyads package."""

from __future__ import annotations


GENERIC_MATERIAL_NAMES: frozenset = frozenset({
    "",
    "...",
    "nan",
    "none",
    "not_found",
    "not found",
    "material",
    "materials",
    "mof",
    "mofs",
    "cof",
    "cofs",
    "metal-organic framework",
    "metal-organic frameworks",
    "metal organic framework",
    "metal organic frameworks",
    "metal-organic framework (mof)",
    "metal-organic frameworks (mofs)",
    "covalent organic framework",
    "covalent organic frameworks",
    "covalent organic framework (cof)",
    "covalent organic frameworks (cofs)",
    "nitrogen",
})
