"""Benchmark evaluation for pyads extraction accuracy.

Compares extracted ``adsorption_data.json`` output against a manually verified
ground-truth file and reports per-field precision, recall, and F1 scores.

Ground-truth format (``data/benchmark/ground_truth.json``):

.. code-block:: json

    {
      "version": 1,
      "papers": [
        {
          "doi": "10.1073/pnas.0602439103",
          "materials": [
            {
              "material": "ZIF-8",
              "surface_area": {"value": 1630.0, "unit": "m2/g"},
              ...
            }
          ]
        }
      ]
    }

The extracted-results file is the standard ``adsorption_data.json`` produced by
``pyads``.  Papers are matched by DOI; materials within a paper are matched by
name (exact first, then substring fallback).

Numeric fields (``surface_area``, ``pore_volume``, ``pore_size``) are scored
within a configurable fractional tolerance (default ±5 %).  String fields
(``material``) use case-insensitive equality.  List fields (``gases``) require
full ground-truth coverage (all expected gases must be present).

Usage::

    python -m pyads.benchmark data/extracted/adsorption_data.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

NUMERIC_FIELDS = ("surface_area", "pore_volume", "pore_size")
DEFAULT_GROUND_TRUTH = Path(__file__).resolve().parents[1] / "data" / "benchmark" / "ground_truth.json"
DEFAULT_TOLERANCE = 0.05


def _numeric_value(field_dict: Any) -> float | None:
    """Return the numeric value from a {value, unit} measurement dict."""
    if not isinstance(field_dict, dict):
        return None
    return field_dict.get("value")


def _within_tolerance(extracted: Any, truth: Any, tolerance: float) -> bool:
    """Return True if *extracted* is within *tolerance* fraction of *truth*."""
    if extracted is None or truth is None:
        return False
    if truth == 0:
        return extracted == 0
    return abs(extracted - truth) / abs(truth) <= tolerance


def _find_matching_material(
    extracted_materials: list[dict[str, Any]], gt_name: str
) -> dict[str, Any] | None:
    """Find the extracted material whose name best matches *gt_name*.

    Tries exact case-insensitive match first, then substring containment.
    Returns ``None`` when no plausible match exists.
    """
    if not extracted_materials or not gt_name:
        return None
    gt_lower = gt_name.lower().strip()
    for mat in extracted_materials:
        if (mat.get("material") or "").lower().strip() == gt_lower:
            return mat
    for mat in extracted_materials:
        name = (mat.get("material") or "").lower().strip()
        if gt_lower in name or name in gt_lower:
            return mat
    return None


def _score_numeric(gt_val: Any, ext_val: Any, tolerance: float) -> str:
    """Return a score label for one numeric measurement field."""
    if gt_val is None:
        return "correct" if ext_val is None else "extra"
    if ext_val is None:
        return "missing"
    return "correct" if _within_tolerance(ext_val, gt_val, tolerance) else "wrong"


def _score_gases(gt_gases: set, ext_gases: set) -> str:
    """Return a score label for the gases list field."""
    if not gt_gases:
        return "correct" if not ext_gases else "extra"
    if not ext_gases:
        return "missing"
    overlap = gt_gases & ext_gases
    if overlap == gt_gases:
        return "correct"
    return "partial" if overlap else "wrong"


def evaluate_material(
    extracted_mat: dict[str, Any] | None,
    gt_mat: dict[str, Any],
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, str]:
    """Compare one extracted material against its ground-truth counterpart.

    Returns a dict mapping each field to one of:
    ``"correct"``, ``"wrong"``, ``"missing"``, ``"extra"``, ``"partial"``.
    """
    if extracted_mat is None:
        return {field: "missing" for field in (*NUMERIC_FIELDS, "material", "gases")}

    scores: dict[str, str] = {}

    ext_name = (extracted_mat.get("material") or "").lower().strip()
    gt_name = (gt_mat.get("material") or "").lower().strip()
    if ext_name == gt_name:
        scores["material"] = "correct"
    elif not ext_name:
        scores["material"] = "missing"
    else:
        scores["material"] = "wrong"

    for field in NUMERIC_FIELDS:
        scores[field] = _score_numeric(
            _numeric_value(gt_mat.get(field)),
            _numeric_value(extracted_mat.get(field)),
            tolerance,
        )

    gt_gases = {g.lower() for g in (gt_mat.get("gases") or [])}
    ext_gases = {g.lower() for g in (extracted_mat.get("gases") or [])}
    scores["gases"] = _score_gases(gt_gases, ext_gases)

    return scores


def aggregate_scores(
    all_scores: list[dict[str, str]]
) -> dict[str, dict[str, Any]]:
    """Compute precision, recall, and F1 per field across all evaluated materials.

    - True positive (TP): ``"correct"``
    - False positive (FP): ``"wrong"`` or ``"extra"``
    - False negative (FN): ``"wrong"`` or ``"missing"``

    ``"partial"`` counts as both FP and FN (half credit on each side).
    """
    fields = (*NUMERIC_FIELDS, "material", "gases")
    summary: dict[str, dict[str, Any]] = {}
    for field in fields:
        tp = sum(1 for s in all_scores if s.get(field) == "correct")
        fp = sum(1 for s in all_scores if s.get(field) in ("wrong", "extra")) + \
             sum(0.5 for s in all_scores if s.get(field) == "partial")
        fn = sum(1 for s in all_scores if s.get(field) in ("wrong", "missing")) + \
             sum(0.5 for s in all_scores if s.get(field) == "partial")
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        summary[field] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }
    return summary


def run_evaluation(
    extracted_json_path: str | Path,
    ground_truth_path: str | Path = DEFAULT_GROUND_TRUTH,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """Load extracted results and ground truth, then return per-field accuracy metrics.

    Papers are matched by DOI.  Materials within each paper are matched by name.
    """
    extracted: list[dict[str, Any]] = json.loads(
        Path(extracted_json_path).read_text(encoding="utf-8")
    )
    gt_data: dict[str, Any] = json.loads(
        Path(ground_truth_path).read_text(encoding="utf-8")
    )

    extracted_by_doi = {
        (p.get("doi") or "").lower().strip(): p
        for p in extracted
        if (p.get("doi") or "").strip()
    }

    all_material_scores: list[dict[str, str]] = []
    unmatched_papers: list[str] = []

    for gt_paper in gt_data.get("papers", []):
        doi = (gt_paper.get("doi") or "").lower().strip()
        ext_paper = extracted_by_doi.get(doi)
        if ext_paper is None:
            unmatched_papers.append(doi)
            for gt_mat in gt_paper.get("materials", []):
                all_material_scores.append(evaluate_material(None, gt_mat, tolerance))
            continue

        ext_materials = ext_paper.get("materials", [])
        for gt_mat in gt_paper.get("materials", []):
            gt_name = gt_mat.get("material") or ""
            ext_mat = _find_matching_material(ext_materials, gt_name)
            all_material_scores.append(evaluate_material(ext_mat, gt_mat, tolerance))

    return {
        "papers_evaluated": len(gt_data.get("papers", [])),
        "materials_evaluated": len(all_material_scores),
        "unmatched_papers": unmatched_papers,
        "tolerance": tolerance,
        "field_metrics": aggregate_scores(all_material_scores),
    }


def print_report(report: dict[str, Any]) -> None:
    """Print a formatted benchmark evaluation report to stdout."""
    print(
        f"\nBenchmark: {report['papers_evaluated']} papers, "
        f"{report['materials_evaluated']} materials, "
        f"numeric tolerance ±{report['tolerance'] * 100:.0f}%"
    )
    print("-" * 60)
    print(f"{'Field':<22} {'Precision':>10} {'Recall':>8} {'F1':>8}")
    print("-" * 60)
    for field, m in report["field_metrics"].items():
        print(f"{field:<22} {m['precision']:>10.3f} {m['recall']:>8.3f} {m['f1']:>8.3f}")
    print("-" * 60)
    if report["unmatched_papers"]:
        print(f"Unmatched (DOI not in extracted): {report['unmatched_papers']}")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for the benchmark evaluation."""
    parser = argparse.ArgumentParser(
        description="Evaluate pyads extraction accuracy against ground-truth data."
    )
    parser.add_argument("extracted_json", help="Path to adsorption_data.json from pyads.")
    parser.add_argument(
        "--ground-truth",
        default=str(DEFAULT_GROUND_TRUTH),
        help="Path to ground_truth.json (default: data/benchmark/ground_truth.json).",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_TOLERANCE,
        help="Fractional tolerance for numeric comparison (default: 0.05 = 5%%).",
    )
    args = parser.parse_args(argv)
    report = run_evaluation(args.extracted_json, args.ground_truth, args.tolerance)
    print_report(report)


if __name__ == "__main__":
    main()
