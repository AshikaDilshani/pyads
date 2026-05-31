"""Agentic extraction loop: observe-reason-act for adaptive field recovery.

The standard two-pass extraction in pyads.extractor applies a fixed strategy:
first pass (broad extraction) + second pass (strict validation).  This module
adds a third decision layer that makes the extraction process genuinely agentic:

    Observe  → inspect per-field confidence scores after the two-pass result.
    Reason   → identify which numeric fields are still low-confidence and why.
    Act      → issue a targeted third query focused only on those fields,
               then merge the improved values back into the record.

Why a third targeted pass?
--------------------------
The standard validation pass corrects gross unit errors (e.g. surface area
reported in cm³/g instead of m²/g).  A harder class of error occurs when a
paper reports multiple measurements — activation conditions at 200 °C, BET
measurement at 77 K — and the LLM conflates them.  A targeted query that
restricts both the field list and the evidence window reliably resolves this:
shorter context → less noise → more accurate extraction.

Cost control
------------
The targeted pass runs at most once per record and only when at least one
numeric field has low confidence.  Records that pass the standard two passes
cleanly incur no additional API cost.

Usage
-----
    from pyads.agent import adaptive_extract

    record, confidence, usage = adaptive_extract(
        text=ocr_text,
        source_file="paper.txt",
        client=mistral_client,
        model="mistral-small-latest",
    )
"""

from __future__ import annotations

import logging
from typing import Any

from pyads.confidence import compute_confidence
from pyads.extractor import (
    VALIDATION_MAX_CHARS,
    _add_usage,
    _chat_json_with_retries,
    _evidence_text,
    _normalize_measure,
    extract_data_from_text,
    validate_record_from_text,
)


_NUMERIC_FIELDS = ("surface_area", "pore_volume", "pore_size")

_TARGETED_PROMPT = """
You are re-extracting specific adsorption fields from a scientific paper.

Focus ONLY on these fields: {fields}

Return a JSON object containing only those fields. Use null for any field
not clearly and unambiguously present in the evidence.

Field rules:
- surface_area: BET surface area only. Unit must be m²/g, m^2/g, or m2/g.
  If the evidence mentions only cm³/g or cm³/g-type values, return null.
- pore_volume: total pore volume. Unit must be cm³/g, cm3/g, or cc/g.
- pore_size: pore diameter or width. Unit is typically nm or Å.

Return JSON only. No explanation.

Evidence:
{evidence}
""".strip()


def _low_confidence_numeric_fields(confidence_report: dict[str, Any]) -> list[str]:
    """Return numeric field names whose confidence is 'low'."""
    return [
        field
        for field in _NUMERIC_FIELDS
        if confidence_report.get("fields", {}).get(field) == "low"
    ]


def _apply_targeted(
    base: dict[str, Any],
    targeted_raw: dict[str, Any],
    fields: list[str],
    source_file: str,
) -> dict[str, Any]:
    """Merge targeted extraction results into the base record for the given fields."""
    merged = dict(base)
    for field in fields:
        raw_value = targeted_raw.get(field)
        if field == "surface_area":
            candidate = _normalize_measure(
                raw_value, allowed_units=("m2/g", "m^2/g", "m²/g", "sqm/g")
            )
        elif field == "pore_volume":
            candidate = _normalize_measure(
                raw_value, allowed_units=("cm3/g", "cm^3/g", "cm³/g", "cc/g")
            )
        else:
            candidate = _normalize_measure(raw_value)

        if candidate.get("value") is not None:
            merged[field] = candidate
            logging.info(
                "Agent: updated %s for %s → %s %s",
                field,
                source_file,
                candidate["value"],
                candidate["unit"],
            )
    return merged


def adaptive_extract(
    text: str,
    source_file: str,
    client: Any,
    model: str,
    max_chars: int = 30000,
    validation_max_chars: int = VALIDATION_MAX_CHARS,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run adaptive agentic extraction with targeted retry for low-confidence fields.

    Observe, reason, and act on confidence scores after the standard two-pass
    extraction, issuing a focused third query when numeric fields remain uncertain.

    Returns a tuple of (record, confidence_report, usage_total).
    """
    usage_total: dict[str, int] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    logging.info("Agent: first pass for %s", source_file)
    first_record, usage1 = extract_data_from_text(
        text[:max_chars], source_file, client, model
    )
    _add_usage(usage_total, usage1)

    logging.info("Agent: validation pass for %s", source_file)
    second_record, usage2 = validate_record_from_text(
        first_record, text, client, model, validation_max_chars
    )
    _add_usage(usage_total, usage2)

    confidence = compute_confidence(first_record, second_record)
    low_fields = _low_confidence_numeric_fields(confidence)

    if low_fields:
        logging.info(
            "Agent: low-confidence numeric fields for %s: %s — running targeted pass",
            source_file,
            low_fields,
        )
        evidence = _evidence_text(text, validation_max_chars)
        prompt = _TARGETED_PROMPT.format(
            fields=", ".join(low_fields),
            evidence=evidence,
        )
        targeted_raw, usage3 = _chat_json_with_retries(
            client,
            model,
            prompt,
            "Extract only the requested fields. Return JSON only.",
        )
        _add_usage(usage_total, usage3)

        merged = _apply_targeted(second_record, targeted_raw, low_fields, source_file)
        final_confidence = compute_confidence(second_record, merged)
        merged["confidence"] = final_confidence
        return merged, final_confidence, usage_total

    second_record["confidence"] = confidence
    return second_record, confidence, usage_total
