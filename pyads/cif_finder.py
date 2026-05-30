"""Download CIF files for materials listed in adsorption_data.json/xlsx,
or for a single manually specified material.

Open data source: Crystallography Open Database (COD), no API key required.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "adsorption_data.xlsx"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "cif_file"
DEFAULT_REPORT = DEFAULT_OUTPUT_DIR / "cif_download_report.csv"

COD_RESULT_URL = "https://www.crystallography.net/cod/result"
COD_CIF_URL = "https://www.crystallography.net/cod/{cod_id}.cif"

MATERIAL_COLUMNS = (
    "material",
    "Material",
    "Material name studied",
    "material_name",
    "adsorbent",
    "Adsorbent",
)
DOI_COLUMNS = ("doi", "DOI", "Doi")
TITLE_COLUMNS = ("title", "Title", "Title of article")

GENERIC_MATERIALS = {
    "",
    "nan",
    "none",
    "not_found",
    "not found",
    "material",
    "materials",
    "cof",
    "cofs",
    "mof",
    "mofs",
    "covalent organic frameworks",
    "covalent organic frameworks (cofs)",
    "metal-organic framework",
    "metal organic framework",
}


def clean_text(value: object) -> str:
    """Collapse whitespace and convert value to a stripped string."""
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def safe_filename(value: str, max_length: int = 120) -> str:
    """Convert a material name into a safe filesystem filename."""
    name = clean_text(value)
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._ ")
    return name[:max_length] or "unknown_material"


def read_input_table(input_path: Path) -> pd.DataFrame:
    """Read adsorption data from a JSON or Excel file into a DataFrame."""
    suffix = input_path.suffix.lower()
    if suffix == ".json":
        records = json.loads(input_path.read_text(encoding="utf-8"))
        return pd.json_normalize(records)
    return pd.read_excel(input_path)


def first_existing_column(
    columns: Iterable[str], candidates: Iterable[str], label: str
) -> str:
    """Return the first candidate column name that exists, or raise KeyError."""
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    raise KeyError(f"No {label} column found. Available columns: {list(columns)}")


def useful_material(material: str) -> bool:
    """Return True if the material name is specific enough to search for."""
    normalized = material.strip().lower()
    return len(normalized) >= 3 and normalized not in GENERIC_MATERIALS


def unique_material_rows(df: pd.DataFrame) -> list[dict[str, str]]:
    """Deduplicate and filter a DataFrame down to searchable material rows."""
    material_column = first_existing_column(df.columns, MATERIAL_COLUMNS, "material")
    doi_column = next((column for column in DOI_COLUMNS if column in df.columns), "")
    title_column = next((column for column in TITLE_COLUMNS if column in df.columns), "")

    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for _, row in df.iterrows():
        material = clean_text(row.get(material_column, ""))
        key = material.lower()

        if key in seen or not useful_material(material):
            continue

        seen.add(key)
        rows.append(
            {
                "material": material,
                "doi": clean_text(row.get(doi_column, "")) if doi_column else "",
                "title": clean_text(row.get(title_column, "")) if title_column else "",
            }
        )

    return rows


def candidate_queries(material: str, doi: str, title: str) -> list[str]:
    """Build an ordered list of COD search queries for a material."""
    queries = [material]

    compact_material = re.sub(r"[^A-Za-z0-9+\-.,()/@]+", " ", material).strip()
    if compact_material and compact_material != material:
        queries.append(compact_material)

    if doi and doi.lower() not in {"not_found", "not found", "nan"}:
        queries.append(doi.replace("_", "/"))

    if title and title.lower() not in {"not_found", "not found", "nan"} and len(title) > 12:
        queries.append(title[:160])

    unique_queries: list[str] = []
    seen: set[str] = set()
    for query in queries:
        query = query.strip()
        key = query.lower()
        if query and key not in seen:
            unique_queries.append(query)
            seen.add(key)

    return unique_queries


def cod_search(
    session: requests.Session, query: str, limit: int, timeout: int
) -> list[dict]:
    """Query the COD REST API and return up to *limit* results."""
    response = session.get(
        COD_RESULT_URL,
        params={"text": query, "format": "json"},
        timeout=timeout,
    )
    if response.status_code != 200:
        return []

    payload = response.json()
    if not isinstance(payload, list):
        return []

    return payload[:limit]


def choose_best_cod_result(
    results: list[dict], material: str, doi: str
) -> dict | None:
    """Pick the COD result whose metadata best matches the material name or DOI."""
    material_lower = material.lower()
    doi_lower = doi.lower()

    for result in results:
        haystack = " ".join(
            str(result.get(field, "") or "")
            for field in ("title", "text", "chemical_name", "mineral", "formula", "journal")
        ).lower()
        if doi_lower and doi_lower not in {"not_found", "not found", "nan"} and doi_lower in haystack:
            return result
        if material_lower in haystack:
            return result

    if results:
        return results[0]

    return None


def cod_identifier(result: dict) -> str:
    """Extract the COD numeric identifier from a search result."""
    return str(result.get("file") or result.get("id") or "").strip()


def looks_like_cif(text: str) -> bool:
    """Return True if the text looks like a valid CIF file."""
    head = text[:2000].lower()
    return "data_" in head and (
        "_cell_length" in head
        or "_atom_site" in head
        or "_symmetry" in head
        or "_space_group" in head
    )


def ensure_unique_path(path: Path, identifier: str) -> Path:
    """Append a suffix to avoid overwriting an existing valid CIF file."""
    if not path.exists():
        return path
    suffix = safe_filename(identifier) if identifier else "duplicate"
    return path.with_name(f"{path.stem}_{suffix}{path.suffix}")


def download_cod_cif(
    session: requests.Session,
    cod_id: str,
    target_path: Path,
    timeout: int,
) -> Path | None:
    """Download one CIF from COD and write it to *target_path*."""
    response = session.get(COD_CIF_URL.format(cod_id=cod_id), timeout=timeout)
    if response.status_code != 200:
        return None
    if not looks_like_cif(response.text):
        return None
    if target_path.exists() and looks_like_cif(
        target_path.read_text(encoding="utf-8", errors="replace")
    ):
        return target_path

    final_path = ensure_unique_path(target_path, cod_id)
    final_path.write_text(response.text, encoding="utf-8", errors="replace")
    return final_path


def make_report_row(
    material: str,
    status: str,
    query: str,
    identifier: str = "",
    cif_file: str = "",
    message: str = "",
) -> dict[str, str]:
    """Build a download report row dict."""
    return {
        "material": material,
        "status": status,
        "source": "COD",
        "query": query,
        "identifier": identifier,
        "cif_file": cif_file,
        "message": message,
    }


def find_cif_for_material(
    session: requests.Session,
    material_row: dict[str, str],
    output_dir: Path,
    max_results: int,
    timeout: int,
) -> dict[str, str]:
    """Search COD for a material and download the best matching CIF."""
    material = material_row["material"]
    target_path = output_dir / f"{safe_filename(material)}.cif"
    queries = candidate_queries(material, material_row["doi"], material_row["title"])

    for query in queries:
        results = cod_search(session, query, max_results, timeout)
        best = choose_best_cod_result(results, material, material_row["doi"])

        if best is None:
            continue

        cod_id = cod_identifier(best)
        if not cod_id:
            continue

        cif_path = download_cod_cif(session, cod_id, target_path, timeout)
        if cif_path is None:
            continue

        return make_report_row(
            material=material,
            status="downloaded",
            query=query,
            identifier=cod_id,
            cif_file=str(cif_path),
        )

    return make_report_row(
        material=material,
        status="not_found",
        query=" | ".join(queries),
        message="No COD CIF match was found.",
    )


def write_report(rows: list[dict[str, str]], report_path: Path) -> None:
    """Write the CIF download report to a CSV file."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    for old_report in report_path.parent.glob(f"{report_path.stem}_*.csv"):
        old_report.unlink()
    fieldnames = ["material", "status", "source", "query", "identifier", "cif_file", "message"]
    with report_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_session(retries: int, backoff: float) -> requests.Session:
    """Create a requests Session with retry logic for transient COD failures."""
    session = requests.Session()
    retry_policy = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry_policy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "pyads-cif-finder/1.0"})
    return session


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the CIF finder tool."""
    parser = argparse.ArgumentParser(
        description="Find and download CIF files for materials from adsorption data."
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help="Path to adsorption_data.xlsx or JSON.",
    )
    parser.add_argument(
        "--material",
        default="",
        help="Single material name to search without reading Excel.",
    )
    parser.add_argument("--doi", default="", help="Optional DOI for --material searches.")
    parser.add_argument(
        "--title",
        default="",
        help="Optional paper title for --material searches.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Folder for downloaded CIF files.",
    )
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="CSV report path.")
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Maximum COD candidates per query.",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between materials in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="HTTP retries for transient COD failures.",
    )
    parser.add_argument(
        "--backoff",
        type=float,
        default=1.0,
        help="Retry backoff factor in seconds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print unique material names only.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Entry point for CIF file downloading."""
    args = parse_args(argv)
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    report_path = Path(args.report)

    if args.material:
        material_rows = [
            {
                "material": clean_text(args.material),
                "doi": clean_text(args.doi),
                "title": clean_text(args.title),
            }
        ]
    else:
        df = read_input_table(input_path)
        material_rows = unique_material_rows(df)

    if args.dry_run:
        print(f"Useful unique material names found: {len(material_rows)}")
        for row in material_rows:
            print(row["material"])
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    session = make_session(args.retries, args.backoff)

    report_rows: list[dict[str, str]] = []
    for row in material_rows:
        print(f"Searching CIF for: {row['material']}")
        result = find_cif_for_material(
            session=session,
            material_row=row,
            output_dir=output_dir,
            max_results=args.max_results,
            timeout=args.timeout,
        )
        report_rows.append(result)
        write_report(report_rows, report_path)
        print(f"  {result['status']}: {result['cif_file'] or result['message']}")
        time.sleep(args.delay)

    write_report(report_rows, report_path)

    downloaded = sum(1 for row in report_rows if row["status"] == "downloaded")
    print(f"Downloaded {downloaded}/{len(report_rows)} CIF file(s).")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
