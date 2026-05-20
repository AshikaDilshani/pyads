"""
Configuration for the Mistral PDF OCR runner.
"""

import ast
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


def _has_dotenv_assignments(path):
    if not path.exists():
        return False

    prefixes = ("MISTRAL_API_KEY=", "LOG_LEVEL=", "PDF_DIR=", "TEXT_DIR=")
    return any(
        line.strip().startswith(prefixes)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def _read_legacy_api_key(path):
    """
    Support the current .env shape: api_key = "...".
    This parses assignments only and does not execute the file.
    """
    if not path.exists():
        return None

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return None

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id in {"api_key", "MISTRAL_API_KEY"}
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                return node.value.value
    return None


def _path_from_env(name, default):
    path = Path(os.getenv(name, default))
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _default_pdf_dir():
    legacy_pdf_dir = PROJECT_ROOT / "PDF"
    if legacy_pdf_dir.exists():
        return legacy_pdf_dir
    return PROJECT_ROOT / "data" / "pdfs"


if _has_dotenv_assignments(ENV_PATH):
    load_dotenv(ENV_PATH)


MISTRAL_API_KEY = (
    os.getenv("MISTRAL_API_KEY")
    or os.getenv("MISTRAL_API")
    or _read_legacy_api_key(ENV_PATH)
)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PDF_DIR = _path_from_env("PDF_DIR", _default_pdf_dir())
TEXT_DIR = _path_from_env("TEXT_DIR", PROJECT_ROOT / "data" / "text")
EXTRACTION_DIR = _path_from_env("EXTRACTION_DIR", PROJECT_ROOT)
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "mistral-small-latest")
EXTRACTION_MAX_CHARS = int(os.getenv("EXTRACTION_MAX_CHARS", "30000"))
VALIDATION_MAX_CHARS = int(os.getenv("VALIDATION_MAX_CHARS", "20000"))
