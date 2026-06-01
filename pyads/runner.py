"""
End-to-end runner for the pyads project.

Pipeline:
1. OCR PDFs with Mistral.
2. Extract adsorption data from OCR text.
3. Download CIF files from open sources.
4. Analyze downloaded/local CIF files.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from pyads.config import (
    EXTRACTION_DIR,
    EXTRACTION_MAX_CHARS,
    EXTRACTION_MODEL,
    PDF_DIR,
    TEXT_DIR,
    VALIDATION_MAX_CHARS,
)

from pyads.cif_analyzer import DEFAULT_ANALYSIS_REPORT, DEFAULT_CIF_DIR, DEFAULT_XRD_DIR
from pyads.cif_analyzer import main as analyze_cif_files
from pyads.cif_finder import DEFAULT_OUTPUT_DIR as DEFAULT_CIF_OUTPUT_DIR
from pyads.cif_finder import DEFAULT_REPORT as DEFAULT_CIF_DOWNLOAD_REPORT
from pyads.cif_finder import (
    find_cif_for_material,
    make_session,
    read_input_table,
    unique_material_rows,
    write_report,
)
from pyads.agent import adaptive_extract
from pyads.extractor import _add_usage, save_outputs, process_text_files
from pyads.ocr import process_pdfs


DEFAULT_CIF_INPUT_JSON = EXTRACTION_DIR / "adsorption_data.json"


def _run_agentic_extraction(args: argparse.Namespace) -> None:
    """Run the agentic extraction loop and print token usage and output paths."""
    import logging  # pylint: disable=import-outside-toplevel

    try:
        from mistralai import Mistral  # pylint: disable=import-outside-toplevel
    except ImportError:
        from mistralai.client import Mistral  # pylint: disable=import-outside-toplevel

    from pyads.config import MISTRAL_API_KEY  # pylint: disable=import-outside-toplevel

    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY is not set. Add it to .env.")

    text_dir = Path(args.text_dir)
    text_files = sorted(text_dir.glob("*.txt"))
    if args.limit:
        text_files = text_files[: args.limit]
    if not text_files:
        raise FileNotFoundError(f"No .txt files found in {text_dir}")

    client = Mistral(api_key=MISTRAL_API_KEY)
    records = []
    usage_total: dict = {
        "total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }

    for text_path in text_files:
        logging.info("Agentic extraction: %s", text_path.name)
        text = text_path.read_text(encoding="utf-8", errors="replace")
        record, _conf, usage = adaptive_extract(
            text=text,
            source_file=text_path.name,
            client=client,
            model=args.model,
            max_chars=args.max_chars,
            validation_max_chars=args.validation_max_chars,
        )
        _add_usage(usage_total["total"], usage)
        records.append(record)

    outputs = save_outputs(records, usage_total, args.output_dir)
    print(f"Saved JSON: {outputs['json']}")
    print(f"Saved Excel: {outputs['excel']}")
    print(f"Saved usage summary: {outputs['usage']}")
    flat = usage_total["total"]
    if flat.get("total_tokens"):
        print(
            f"Mistral LLM tokens: {flat['prompt_tokens']} prompt, "
            f"{flat['completion_tokens']} completion, "
            f"{flat['total_tokens']} total."
        )
    _maybe_print_token_cost(usage_total)


def _maybe_print_token_cost(usage: dict) -> None:
    flat_usage = usage.get("total", {})
    prompt_tokens = int(flat_usage.get("prompt_tokens", 0) or 0)
    completion_tokens = int(flat_usage.get("completion_tokens", 0) or 0)
    if not (prompt_tokens or completion_tokens):
        return

    prompt_price = float(os.getenv("MISTRAL_PROMPT_PRICE_PER_MTOK", "0") or 0.0)
    completion_price = float(os.getenv("MISTRAL_COMPLETION_PRICE_PER_MTOK", "0") or 0.0)
    if prompt_price <= 0 and completion_price <= 0:
        return

    estimated_cost = (
        (prompt_tokens / 1_000_000.0) * prompt_price
        + (completion_tokens / 1_000_000.0) * completion_price
    )
    print(
        "Estimated extraction token cost: "
        f"${estimated_cost:.6f} "
        f"(prompt ${prompt_price}/Mtok, completion ${completion_price}/Mtok)."
    )


def _list_pdfs_for_ocr(pdf_dir: Path) -> list[Path]:
    if not pdf_dir.exists() or not pdf_dir.is_dir():
        raise FileNotFoundError(f"PDF directory does not exist: {pdf_dir}")

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in {pdf_dir}")
    return pdf_files


def run_ocr(args: argparse.Namespace) -> None:
    """Run the Mistral OCR stage and print page and byte counts."""
    pdf_dir = Path(args.pdf_dir)
    _list_pdfs_for_ocr(pdf_dir)

    usage = process_pdfs(pdf_dir=pdf_dir, text_dir=Path(args.text_dir))
    if usage:
        print(
            "Mistral OCR usage: "
            f"{usage.get('pages_processed', 0)} pages processed, "
            f"{usage.get('doc_size_bytes', 0)} document bytes uploaded."
        )
        print("OCR API did not return token counts for this endpoint.")


def run_extraction(args: argparse.Namespace) -> None:
    """Run the LLM extraction stage and print token usage and output paths."""
    if getattr(args, "agentic", False):
        _run_agentic_extraction(args)
        return
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
    _maybe_print_token_cost(usage)


def run_cif_download(args: argparse.Namespace) -> None:
    """Search COD and download CIF files for each material in the extraction output."""
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
    """Analyse downloaded CIF files with gemmi/pymatgen and write the analysis report."""
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

    analyze_cif_files(analyzer_args)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the full pyads pipeline."""
    parser = argparse.ArgumentParser(description="Run the full pyads workflow.")
    parser.add_argument("--skip-ocr", action="store_true", help="Skip Mistral OCR.")
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip adsorption data extraction.",
    )
    parser.add_argument("--skip-cif-download", action="store_true", help="Skip CIF download.")
    parser.add_argument("--skip-cif-analysis", action="store_true", help="Skip CIF analysis.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List PDFs that would be processed and exit without API calls.",
    )
    parser.add_argument(
        "--pdf-dir",
        default=str(PDF_DIR),
        help="Directory containing PDF files for OCR.",
    )

    parser.add_argument(
        "--text-dir",
        default=str(TEXT_DIR),
        help="Directory containing OCR .txt files.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(EXTRACTION_DIR),
        help="Directory for JSON and Excel outputs.",
    )
    parser.add_argument(
        "--model",
        default=EXTRACTION_MODEL,
        help="Mistral chat model for extraction.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=EXTRACTION_MAX_CHARS,
        help="Maximum characters per text file.",
    )
    parser.add_argument(
        "--validation-max-chars",
        type=int,
        default=VALIDATION_MAX_CHARS,
        help="Maximum evidence characters for validation pass.",
    )
    parser.add_argument(
        "--second-pass",
        action="store_true",
        help="Run strict validation pass after first extraction.",
    )
    parser.add_argument(
        "--agentic",
        action="store_true",
        help=(
            "Use the agentic extraction loop: two-pass + targeted retry for "
            "low-confidence fields and known-material range validation."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Only process the first N text files during extraction.",
    )

    parser.add_argument(
        "--cif-input",
        default=str(DEFAULT_CIF_INPUT_JSON),
        help="adsorption_data JSON/XLSX for CIF search.",
    )
    parser.add_argument(
        "--cif-output-dir",
        default=str(DEFAULT_CIF_OUTPUT_DIR),
        help="Folder for downloaded CIF files.",
    )
    parser.add_argument(
        "--cif-download-report",
        default=str(DEFAULT_CIF_DOWNLOAD_REPORT),
        help="CIF download CSV report.",
    )
    parser.add_argument(
        "--cif-max-results",
        type=int,
        default=5,
        help="Maximum COD candidates per query.",
    )
    parser.add_argument("--cif-timeout", type=int, default=30, help="COD HTTP timeout in seconds.")
    parser.add_argument(
        "--cif-retries",
        type=int,
        default=3,
        help="HTTP retries for transient COD failures.",
    )
    parser.add_argument(
        "--cif-backoff",
        type=float,
        default=1.0,
        help="Retry backoff factor in seconds.",
    )

    parser.add_argument(
        "--cif-dir",
        default=str(DEFAULT_CIF_DIR),
        help="Folder containing CIF files for analysis.",
    )
    parser.add_argument(
        "--cif-analysis-report",
        default=str(DEFAULT_ANALYSIS_REPORT),
        help="CIF analysis CSV report.",
    )
    parser.add_argument(
        "--xrd-dir",
        default=str(DEFAULT_XRD_DIR),
        help="Folder for simulated XRD CSV files.",
    )
    parser.add_argument("--xrd-wavelength", default="CuKa", help="Pymatgen XRD wavelength.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Run the full pyads pipeline: OCR → extraction → CIF download → CIF analysis."""
    args = parse_args(argv)
    pdf_dir = Path(args.pdf_dir)

    if args.dry_run:
        pdf_files = _list_pdfs_for_ocr(pdf_dir)
        print(f"Dry run: {len(pdf_files)} PDF file(s) found in {pdf_dir}")
        for pdf_path in pdf_files:
            print(pdf_path)
        return

    if not args.skip_ocr:
        print("\n=== OCR PDFs ===")
        run_ocr(args)

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
