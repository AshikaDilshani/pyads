"""
End-to-end runner for the Mistral PDF reader project.

Pipeline:
1. OCR PDFs with Mistral.
2. Extract adsorption data from OCR text.
3. Download CIF files from open sources.
4. Analyze downloaded/local CIF files.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pyads.config import EXTRACTION_DIR, EXTRACTION_MAX_CHARS, EXTRACTION_MODEL, TEXT_DIR, VALIDATION_MAX_CHARS

from cif_file_analyzer import DEFAULT_ANALYSIS_REPORT, DEFAULT_CIF_DIR, DEFAULT_XRD_DIR
from cif_file_analyzer import main as analyze_cif_files
from cif_file_finder import DEFAULT_OUTPUT_DIR as DEFAULT_CIF_OUTPUT_DIR
from cif_file_finder import DEFAULT_REPORT as DEFAULT_CIF_DOWNLOAD_REPORT
from cif_file_finder import find_cif_for_material, make_session, read_input_table, unique_material_rows, write_report


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CIF_INPUT_JSON = PROJECT_ROOT / "adsorption_data.json"


def run_ocr() -> None:
    from pyads.ocr import process_pdfs

    usage = process_pdfs()
    if usage:
        print(
            "Mistral OCR usage: "
            f"{usage.get('pages_processed', 0)} pages processed, "
            f"{usage.get('doc_size_bytes', 0)} document bytes uploaded."
        )
        print("OCR API did not return token counts for this endpoint.")


def run_extraction(args: argparse.Namespace) -> None:
    from pyads.extractor import process_text_files

    _, outputs, usage = process_text_files(
        text_dir=args.text_dir,
        output_dir=args.output_dir,
        model=args.model,
        max_chars=args.max_chars,
        validation_max_chars=args.validation_max_chars,
        second_pass=args.second_pass,
        limit=args.limit,
    )
    print(f"Saved JSON: {outputs['json']}")
    print(f"Saved Excel: {outputs['excel']}")
    print(f"Saved usage summary: {outputs['usage']}")

    flat_usage = usage.get("total", {})
    if flat_usage.get("total_tokens"):
        print(
            "Mistral LLM tokens: "
            f"{flat_usage.get('prompt_tokens', 0)} prompt, "
            f"{flat_usage.get('completion_tokens', 0)} completion, "
            f"{flat_usage.get('total_tokens', 0)} total."
        )
    else:
        print("Mistral LLM token usage was not returned by the API.")


def run_cif_download(args: argparse.Namespace) -> None:
    input_path = Path(args.cif_input)
    output_dir = Path(args.cif_output_dir)
    report_path = Path(args.cif_download_report)

    df = read_input_table(input_path)
    material_rows = unique_material_rows(df)

    output_dir.mkdir(parents=True, exist_ok=True)
    session = make_session(args.cif_retries, args.cif_backoff)

    report_rows: list[dict[str, str]] = []
    for row in material_rows:
        print(f"Searching CIF for: {row['material']}")
        result = find_cif_for_material(
            session=session,
            material_row=row,
            output_dir=output_dir,
            max_results=args.cif_max_results,
            timeout=args.cif_timeout,
        )
        report_rows.append(result)
        write_report(report_rows, report_path)
        print(f"  {result['status']}: {result['cif_file'] or result['message']}")

    downloaded = sum(1 for row in report_rows if row["status"] == "downloaded")
    print(f"Downloaded {downloaded}/{len(report_rows)} CIF file(s).")
    print(f"CIF download report: {report_path}")


def run_cif_analysis(args: argparse.Namespace) -> None:
    analyzer_args = [
        "--cif-dir",
        str(args.cif_dir),
        "--download-report",
        str(args.cif_download_report),
        "--report",
        str(args.cif_analysis_report),
        "--xrd-dir",
        str(args.xrd_dir),
        "--wavelength",
        args.xrd_wavelength,
    ]

    import sys

    original_argv = sys.argv
    sys.argv = ["cif_file_analyzer.py", *analyzer_args]
    try:
        analyze_cif_files()
    finally:
        sys.argv = original_argv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full Mistral PDF reader workflow.")
    parser.add_argument("--skip-ocr", action="store_true", help="Skip Mistral OCR.")
    parser.add_argument("--skip-extraction", action="store_true", help="Skip adsorption data extraction.")
    parser.add_argument("--skip-cif-download", action="store_true", help="Skip CIF download.")
    parser.add_argument("--skip-cif-analysis", action="store_true", help="Skip CIF analysis.")

    parser.add_argument("--text-dir", default=str(TEXT_DIR), help="Directory containing OCR .txt files.")
    parser.add_argument("--output-dir", default=str(EXTRACTION_DIR), help="Directory for JSON and Excel outputs.")
    parser.add_argument("--model", default=EXTRACTION_MODEL, help="Mistral chat model for extraction.")
    parser.add_argument("--max-chars", type=int, default=EXTRACTION_MAX_CHARS, help="Maximum characters per text file.")
    parser.add_argument(
        "--validation-max-chars",
        type=int,
        default=VALIDATION_MAX_CHARS,
        help="Maximum evidence characters for validation pass.",
    )
    parser.add_argument("--second-pass", action="store_true", help="Run strict validation pass after first extraction.")
    parser.add_argument("--limit", type=int, help="Only process the first N text files during extraction.")

    parser.add_argument("--cif-input", default=str(DEFAULT_CIF_INPUT_JSON), help="adsorption_data JSON/XLSX for CIF search.")
    parser.add_argument("--cif-output-dir", default=str(DEFAULT_CIF_OUTPUT_DIR), help="Folder for downloaded CIF files.")
    parser.add_argument("--cif-download-report", default=str(DEFAULT_CIF_DOWNLOAD_REPORT), help="CIF download CSV report.")
    parser.add_argument("--cif-max-results", type=int, default=5, help="Maximum COD candidates per query.")
    parser.add_argument("--cif-timeout", type=int, default=30, help="COD HTTP timeout in seconds.")
    parser.add_argument("--cif-retries", type=int, default=3, help="HTTP retries for transient COD failures.")
    parser.add_argument("--cif-backoff", type=float, default=1.0, help="Retry backoff factor in seconds.")

    parser.add_argument("--cif-dir", default=str(DEFAULT_CIF_DIR), help="Folder containing CIF files for analysis.")
    parser.add_argument("--cif-analysis-report", default=str(DEFAULT_ANALYSIS_REPORT), help="CIF analysis CSV report.")
    parser.add_argument("--xrd-dir", default=str(DEFAULT_XRD_DIR), help="Folder for simulated XRD CSV files.")
    parser.add_argument("--xrd-wavelength", default="CuKa", help="Pymatgen XRD wavelength.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.skip_ocr:
        print("\n=== OCR PDFs ===")
        run_ocr()

    if not args.skip_extraction:
        print("\n=== Extract Adsorption Data ===")
        run_extraction(args)

    if not args.skip_cif_download:
        print("\n=== Download CIF Files ===")
        run_cif_download(args)

    if not args.skip_cif_analysis:
        print("\n=== Analyze CIF Files ===")
        run_cif_analysis(args)


if __name__ == "__main__":
    main()
