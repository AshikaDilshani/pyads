"""Extraction confidence scoring for pyads.

After the two-pass extraction (first LLM pass + strict validation pass),
this module compares the two records field-by-field to estimate how reliable
each extracted value is.

Design rationale
----------------
The Mistral extraction prompt asks for a best-effort extraction.  The
validation prompt then re-examines the evidence and corrects impossible
units or values that are unsupported by the text.  When both passes agree
on a non-null value, the extraction is considered high-confidence.  When the
validation pass *changes* a value (e.g. rejects a surface area because the
unit was cm³/g), it signals that the first extraction was uncertain; the
field is marked low-confidence.  Missing fields (null in both passes) are
labelled "absent" rather than "low" so downstream consumers can distinguish
"could not be extracted" from "was extracted but unreliably".

Confidence levels
-----------------
- ``"high"``   — both passes agree on the same non-null value.
- ``"medium"`` — second pass *added* information the first missed,
                 or the values differ only in whitespace / normalisation.
- ``"low"``    — passes disagree (value, unit, or presence changed).
- ``"absent"`` — null or empty in both passes; field not present in the paper.

The ``overall`` score is ``"high"`` only when every extracted field is high,
``"low"`` if any extracted field is low, otherwise ``"medium"``.
"""

from __future__ import annotations

from typing import Any


_NUMERIC_FIELDS = ("surface_area", "pore_volume", "pore_size")
_SCALAR_FIELDS = ("doi", "title", "year", "material")


def _measure_equal(a: Any, b: Any) -> bool:
    """Return True if two {value, unit} dicts are equivalent."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if not isinstance(a, dict) or not isinstance(b, dict):
        return a == b
    return (
        a.get("value") == b.get("value")
        and str(a.get("unit") or "").strip().lower()
        == str(b.get("unit") or "").strip().lower()
    )


def _measure_absent(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return value.get("value") is None
    return False


def _score_scalar(v1: Any, v2: Any) -> str:
    """Score a simple scalar field."""
    absent1 = v1 is None
    absent2 = v2 is None
    if absent1 and absent2:
        return "absent"
    if v1 == v2:
        return "high"
    if absent1 and not absent2:
        return "medium"
    return "low"


def _score_measure(m1: Any, m2: Any) -> str:
    """Score a {value, unit} measurement field."""
    if _measure_absent(m1) and _measure_absent(m2):
        return "absent"
    if _measure_equal(m1, m2):
        return "high"
    if _measure_absent(m1) and not _measure_absent(m2):
        return "medium"
    return "low"


def _score_list(l1: list, l2: list) -> str:
    """Score a list field (gases, isotherm_temperatures)."""
    empty1 = not l1
    empty2 = not l2
    if empty1 and empty2:
        return "absent"
    if l1 == l2:
        return "high"
    if empty1 and not empty2:
        return "medium"
    return "low"


def score_fields(
    first_record: dict[str, Any], second_record: dict[str, Any]
) -> dict[str, str]:
    """Return a per-field confidence score by comparing two extraction passes.

    Each score is one of: ``"high"``, ``"medium"``, ``"low"``, ``"absent"``.
    """
    scores: dict[str, str] = {}

    for field in _SCALAR_FIELDS:
        scores[field] = _score_scalar(
            first_record.get(field), second_record.get(field)
        )

    for field in _NUMERIC_FIELDS:
        scores[field] = _score_measure(
            first_record.get(field), second_record.get(field)
        )

    scores["gases"] = _score_list(
        list(first_record.get("gases") or []),
        list(second_record.get("gases") or []),
    )
    scores["isotherm_temperatures"] = _score_list(
        list(first_record.get("isotherm_temperatures") or []),
        list(second_record.get("isotherm_temperatures") or []),
    )

    return scores


def overall_confidence(field_scores: dict[str, str]) -> str:
    """Derive an overall confidence label from per-field scores.

    Returns ``"high"`` only if every *extracted* field is high-confidence.
    Returns ``"low"`` if any extracted field is low-confidence.
    Otherwise returns ``"medium"``.
    """
    extracted = [s for s in field_scores.values() if s != "absent"]
    if not extracted:
        return "absent"
    if all(s == "high" for s in extracted):
        return "high"
    if any(s == "low" for s in extracted):
        return "low"
    return "medium"


def compute_confidence(
    first_record: dict[str, Any], second_record: dict[str, Any]
) -> dict[str, Any]:
    """Return a confidence report for one extracted record.

    The report has two keys:
    - ``"overall"`` — one of ``"high"``, ``"medium"``, ``"low"``, ``"absent"``.
    - ``"fields"``  — per-field scores (same labels).

    Pass the *first-pass* and *second-pass* records as arguments.  If only
    a single pass was run, pass the same record twice (scores will all be
    ``"high"`` or ``"absent"``).
    """
    field_scores = score_fields(first_record, second_record)
    return {
        "overall": overall_confidence(field_scores),
        "fields": field_scores,
    }
