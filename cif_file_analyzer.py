"""
Analyze downloaded CIF files and flag whether they plausibly match the
materials requested in cif_download_report.csv.

Libraries used:
- gemmi: CIF syntax/structure validity
- pymatgen: structure analysis and simulated XRD pattern
- ase: optional structure read check
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import re
import sys
import warnings
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CIF_DIR = BASE_DIR / "cif_file"
DEFAULT_DOWNLOAD_REPORT = DEFAULT_CIF_DIR / "cif_download_report.csv"
DEFAULT_ANALYSIS_REPORT = DEFAULT_CIF_DIR / "cif_analysis_report.csv"
DEFAULT_XRD_DIR = DEFAULT_CIF_DIR / "xrd_patterns"

GENERIC_MATERIAL_NAMES = {
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
}

STOP_TOKENS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "metal",
    "organic",
    "framework",
    "frameworks",
    "mof",
    "mofs",
    "cof",
    "cofs",
    "based",
    "material",
    "materials",
}


def dependency_status() -> dict[str, str]:
    packages = ("gemmi", "pymatgen", "ase")
    return {
        package: "installed" if importlib.util.find_spec(package) else "missing"
        for package in packages
    }


def require_core_dependencies() -> None:
    status = dependency_status()
    missing_core = [package for package in ("gemmi", "pymatgen") if status[package] == "missing"]
    if missing_core:
        raise RuntimeError(
            "Missing required package(s): "
            + ", ".join(missing_core)
            + f"\nPython executable running this script:\n  {sys.executable}"
            + "\nInstall them with:\n"
            + f"  \"{sys.executable}\" -m pip install gemmi pymatgen ase"
            + "\nOr run this project with the existing venv:\n"
            + "  ..\\venv\\Scripts\\python.exe cif_file_analyzer.py"
        )


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if len(token) >= 3 and token not in STOP_TOKENS
    }


def normalize_material_name(value: str) -> str:
    """Normalize requested material labels before matching."""
    text = clean_text(value)
    text = re.sub(r"\bCIF\b$", "", text, flags=re.IGNORECASE).strip()
    return text


def safe_float(value: Any) -> float | None:
    text = clean_text(value)
    if not text or text in {".", "?"}:
        return None
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?:\(\d+\))?", text):
        return None
    return float(re.sub(r"\(\d+\)$", "", text))


def load_download_rows(report_path: Path) -> list[dict[str, str]]:
    if not report_path.exists():
        return []

    with report_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def downloaded_cif_rows(cif_dir: Path, report_path: Path) -> list[dict[str, str]]:
    rows = [
        row
        for row in load_download_rows(report_path)
        if clean_text(row.get("status")) == "downloaded" and clean_text(row.get("cif_file"))
    ]

    known_paths = {str(Path(row["cif_file"]).resolve()).lower() for row in rows}
    for cif_path in sorted(cif_dir.glob("*.cif")):
        resolved = str(cif_path.resolve()).lower()
        if resolved in known_paths:
            continue
        rows.append(
            {
                "material": cif_path.stem,
                "status": "downloaded",
                "source": "local_file",
                "query": cif_path.stem,
                "identifier": "",
                "cif_file": str(cif_path),
                "message": "CIF file found locally but not in download report.",
            }
        )

    return rows


def cif_text_metadata(cif_path: Path) -> dict[str, str]:
    text = cif_path.read_text(encoding="utf-8", errors="replace")
    fields = {
        "chemical_name": "",
        "chemical_formula": "",
        "publication_title": "",
    }

    name_matches = re.findall(
        r"_(?:chemical_name_systematic|chemical_name_common|chemical_name_mineral)\s+(.+)",
        text,
        flags=re.IGNORECASE,
    )
    formula_matches = re.findall(
        r"_(?:chemical_formula_sum|chemical_formula_structural|chemical_formula_moiety)\s+(.+)",
        text,
        flags=re.IGNORECASE,
    )
    title_matches = re.findall(
        r"_(?:publ_section_title|citation_title)\s+(.+)",
        text,
        flags=re.IGNORECASE,
    )

    fields["chemical_name"] = first_useful_cif_value(name_matches)
    fields["chemical_formula"] = first_useful_cif_value(formula_matches)
    fields["publication_title"] = first_useful_cif_value(title_matches)

    return fields


def first_useful_cif_value(values: list[str]) -> str:
    """Return the first non-placeholder CIF value."""
    for value in values:
        cleaned = clean_cif_value(value)
        if cleaned:
            return cleaned
    return ""


def clean_cif_value(value: str) -> str:
    value = clean_text(value)
    value = value.strip("'\"")
    if value in {".", "?"}:
        return ""
    return value


def gemmi_summary(cif_path: Path) -> dict[str, Any]:
    import gemmi

    document = gemmi.cif.read_file(str(cif_path))
    block = document.sole_block()

    cell = gemmi.UnitCell(
        safe_float(block.find_value("_cell_length_a")) or 0.0,
        safe_float(block.find_value("_cell_length_b")) or 0.0,
        safe_float(block.find_value("_cell_length_c")) or 0.0,
        safe_float(block.find_value("_cell_angle_alpha")) or 0.0,
        safe_float(block.find_value("_cell_angle_beta")) or 0.0,
        safe_float(block.find_value("_cell_angle_gamma")) or 0.0,
    )

    atom_site_loop = block.find_loop("_atom_site_label")
    atom_count = len(atom_site_loop) if atom_site_loop else 0
    space_group = (
        block.find_value("_space_group_name_H-M_alt")
        or block.find_value("_symmetry_space_group_name_H-M")
        or ""
    )

    return {
        "gemmi_valid": "yes",
        "data_block": block.name,
        "space_group": clean_cif_value(space_group),
        "cell_a": cell.a,
        "cell_b": cell.b,
        "cell_c": cell.c,
        "cell_alpha": cell.alpha,
        "cell_beta": cell.beta,
        "cell_gamma": cell.gamma,
        "cell_volume": cell.volume,
        "atom_site_count": atom_count,
    }


def pymatgen_summary(cif_path: Path, xrd_dir: Path, wavelength: str) -> dict[str, Any]:
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    from pymatgen.core import Structure

    structure = Structure.from_file(str(cif_path))
    composition = structure.composition
    formula = composition.reduced_formula
    density = structure.density

    symmetry_symbol = ""
    crystal_system = ""
    space_group_number = ""

    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    analyzer = SpacegroupAnalyzer(structure, symprec=0.1)
    symmetry_symbol = analyzer.get_space_group_symbol()
    space_group_number = analyzer.get_space_group_number()
    crystal_system = analyzer.get_crystal_system()

    xrd_dir.mkdir(parents=True, exist_ok=True)
    xrd_path = xrd_dir / f"{cif_path.stem}_xrd.csv"
    xrd_pattern = XRDCalculator(wavelength=wavelength).get_pattern(structure)
    with xrd_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["two_theta", "intensity", "hkl", "d_spacing"])
        for two_theta, intensity, hkls, d_spacing in zip(
            xrd_pattern.x,
            xrd_pattern.y,
            xrd_pattern.hkls,
            xrd_pattern.d_hkls,
        ):
            writer.writerow([two_theta, intensity, hkls, d_spacing])

    return {
        "pymatgen_valid": "yes",
        "formula": formula,
        "full_formula": composition.formula,
        "num_sites": len(structure),
        "density_g_cm3": density,
        "pymatgen_space_group": symmetry_symbol,
        "space_group_number": space_group_number,
        "crystal_system": crystal_system,
        "xrd_csv": str(xrd_path),
    }


def ase_summary(cif_path: Path) -> dict[str, Any]:
    if importlib.util.find_spec("ase") is None:
        return {"ase_readable": "not_installed", "ase_formula": "", "ase_atoms": ""}

    from ase.io import read

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"crystal system .* is not interpreted for space group .*",
            category=UserWarning,
        )
        atoms = read(str(cif_path))
    return {
        "ase_readable": "yes",
        "ase_formula": atoms.get_chemical_formula(),
        "ase_atoms": len(atoms),
    }


def material_match_score(material: str, metadata: dict[str, str], formula: str) -> dict[str, Any]:
    material = normalize_material_name(material)
    material_normalized = normalize_text(material)
    if material_normalized in GENERIC_MATERIAL_NAMES:
        return {
            "match_score": 0.0,
            "match_label": "reject_generic_material_name",
            "match_reason": "The requested material name is generic, so a CIF cannot be trusted as exact.",
        }

    metadata_text = " ".join(
        clean_text(value)
        for value in (
            metadata.get("chemical_name"),
            metadata.get("chemical_formula"),
            metadata.get("publication_title"),
            metadata.get("data_block"),
            formula,
        )
    )
    metadata_normalized = normalize_text(metadata_text)
    material_tokens = tokens(material)
    metadata_tokens = tokens(metadata_text)
    if material_normalized and material_normalized in metadata_normalized:
        return {
            "match_score": 1.0,
            "match_label": "likely_match",
            "match_reason": "normalized material name appears in CIF metadata or data block",
        }

    token_overlap = len(material_tokens & metadata_tokens) / max(len(material_tokens), 1)
    text_similarity = SequenceMatcher(
        None,
        material_normalized,
        metadata_normalized,
    ).ratio()
    score = max(token_overlap, text_similarity)

    if score >= 0.65:
        label = "likely_match"
    elif score >= 0.35:
        label = "needs_manual_check"
    else:
        label = "likely_wrong_material"

    reason = (
        f"token_overlap={token_overlap:.2f}; text_similarity={text_similarity:.2f}; "
        f"material_tokens={sorted(material_tokens)}; matched_tokens={sorted(material_tokens & metadata_tokens)}"
    )
    return {
        "match_score": round(score, 3),
        "match_label": label,
        "match_reason": reason,
    }


def make_error_row(row: dict[str, str], cif_path: Path, message: str) -> dict[str, Any]:
    return {
        "material": clean_text(row.get("material")),
        "cif_file": str(cif_path),
        "source": clean_text(row.get("source")),
        "identifier": clean_text(row.get("identifier")),
        "gemmi_valid": "no",
        "pymatgen_valid": "no",
        "ase_readable": "",
        "match_label": "invalid_cif",
        "match_score": 0,
        "match_reason": message,
        "chemical_name": "",
        "chemical_formula": "",
        "publication_title": "",
        "formula": "",
        "full_formula": "",
        "num_sites": "",
        "density_g_cm3": "",
        "space_group": "",
        "pymatgen_space_group": "",
        "space_group_number": "",
        "crystal_system": "",
        "cell_a": "",
        "cell_b": "",
        "cell_c": "",
        "cell_alpha": "",
        "cell_beta": "",
        "cell_gamma": "",
        "cell_volume": "",
        "atom_site_count": "",
        "xrd_csv": "",
        "notes": message,
    }


def analyze_cif(row: dict[str, str], xrd_dir: Path, wavelength: str) -> dict[str, Any]:
    cif_path = Path(clean_text(row.get("cif_file")))
    metadata = cif_text_metadata(cif_path)
    gemmi_data = gemmi_summary(cif_path)
    metadata["data_block"] = clean_text(gemmi_data.get("data_block"))
    pymatgen_data = pymatgen_summary(cif_path, xrd_dir, wavelength)
    ase_data = ase_summary(cif_path)
    match_data = material_match_score(
        clean_text(row.get("material")),
        metadata,
        clean_text(pymatgen_data.get("formula")),
    )

    return {
        "material": clean_text(row.get("material")),
        "cif_file": str(cif_path),
        "source": clean_text(row.get("source")),
        "identifier": clean_text(row.get("identifier")),
        **gemmi_data,
        **pymatgen_data,
        **ase_data,
        **match_data,
        **metadata,
        "notes": clean_text(row.get("message")),
    }


def cleanup_old_reports(report_path: Path) -> None:
    """Remove old generated analysis reports from previous runs."""
    for old_report in report_path.parent.glob(f"{report_path.stem}_*.csv"):
        old_report.unlink()


def write_report(rows: list[dict[str, Any]], report_path: Path) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cleanup_old_reports(report_path)
    fieldnames = [
        "material",
        "match_label",
        "match_score",
        "match_reason",
        "gemmi_valid",
        "pymatgen_valid",
        "ase_readable",
        "source",
        "identifier",
        "cif_file",
        "chemical_name",
        "chemical_formula",
        "publication_title",
        "formula",
        "full_formula",
        "num_sites",
        "density_g_cm3",
        "space_group",
        "pymatgen_space_group",
        "space_group_number",
        "crystal_system",
        "cell_a",
        "cell_b",
        "cell_c",
        "cell_alpha",
        "cell_beta",
        "cell_gamma",
        "cell_volume",
        "atom_site_count",
        "xrd_csv",
        "ase_formula",
        "ase_atoms",
        "data_block",
        "notes",
    ]
    with report_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return report_path


def print_dependency_status() -> None:
    for package, status in dependency_status().items():
        print(f"{package}: {status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze downloaded CIF files.")
    parser.add_argument("--cif-dir", default=str(DEFAULT_CIF_DIR), help="Folder containing downloaded CIF files.")
    parser.add_argument(
        "--download-report",
        default=str(DEFAULT_DOWNLOAD_REPORT),
        help="cif_download_report.csv from cif_file_finder.py.",
    )
    parser.add_argument("--report", default=str(DEFAULT_ANALYSIS_REPORT), help="Output CSV analysis report.")
    parser.add_argument("--xrd-dir", default=str(DEFAULT_XRD_DIR), help="Folder for simulated XRD CSV files.")
    parser.add_argument("--wavelength", default="CuKa", help="Pymatgen XRD wavelength, e.g. CuKa.")
    parser.add_argument("--check-deps", action="store_true", help="Only check installed libraries.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.check_deps:
        print_dependency_status()
        return

    require_core_dependencies()

    cif_dir = Path(args.cif_dir)
    download_report = Path(args.download_report)
    analysis_report = Path(args.report)
    xrd_dir = Path(args.xrd_dir)

    rows = downloaded_cif_rows(cif_dir, download_report)
    if not rows:
        raise RuntimeError(f"No CIF files found in {cif_dir}")

    analyzed_rows: list[dict[str, Any]] = []
    for row in rows:
        cif_path = Path(clean_text(row.get("cif_file")))
        try:
            analyzed_rows.append(analyze_cif(row, xrd_dir, args.wavelength))
        except Exception as exc:
            analyzed_rows.append(make_error_row(row, cif_path, str(exc)))

    saved_report = write_report(analyzed_rows, analysis_report)

    label_counts: dict[str, int] = {}
    for row in analyzed_rows:
        label = clean_text(row.get("match_label"))
        label_counts[label] = label_counts.get(label, 0) + 1

    print(f"Analyzed {len(analyzed_rows)} CIF file(s).")
    for label, count in sorted(label_counts.items()):
        print(f"{label}: {count}")
    print(f"Report: {saved_report}")
    print(f"XRD CSV folder: {xrd_dir}")


if __name__ == "__main__":
    main()
