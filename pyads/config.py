"""Configuration and environment loading for the pyads pipeline."""

import ast
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"


def _candidate_env_paths():
    """Load candidate .env file paths in priority order.

    Includes both the current working directory and the project root so
    installed entry points can still find the .env from a cloned repo.
    """
    cwd = Path.cwd()
    candidates = [
        cwd / ".env",
        cwd / ".env.example",
        ENV_PATH,
        ENV_EXAMPLE_PATH,
    ]
    unique = []
    seen = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _has_dotenv_assignments(path):
    if not path.exists():
        return False

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key.isupper() and key.replace("_", "").isalnum():
            return True
    return False


def _read_legacy_api_key(path):
    """Read an api_key assignment from a Python-style .env file.

    Parses AST assignments only; never executes the file.
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


def _load_env_files():
    """Load environment files in precedence order.

    Order: cwd/.env > cwd/.env.example > project/.env > project/.env.example.
    """
    for path in _candidate_env_paths():
        if _has_dotenv_assignments(path):
            load_dotenv(path, override=False)


def _normalize_api_key(value):
    if not value:
        return None
    key = str(value).strip().strip('"').strip("'")
    if not key:
        return None

    lower = key.lower()
    placeholder_markers = (
        "your_mistral_api_key_here",
        "replace_with_your_api_key",
        "replace_me",
        "<mistral_api_key>",
    )
    if lower in placeholder_markers or "your_mistral_api_key" in lower:
        return None
    return key


def _resolve_api_key():
    values = [
        os.getenv("MISTRAL_API_KEY"),
        os.getenv("MISTRAL_API"),
        *(_read_legacy_api_key(path) for path in _candidate_env_paths()),
    ]
    for value in values:
        normalized = _normalize_api_key(value)
        if normalized:
            return normalized
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


_load_env_files()


MISTRAL_API_KEY = _resolve_api_key()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PDF_DIR = _path_from_env("PDF_DIR", _default_pdf_dir())
TEXT_DIR = _path_from_env("TEXT_DIR", PROJECT_ROOT / "data" / "text")
EXTRACTION_DIR = _path_from_env("EXTRACTION_DIR", PROJECT_ROOT / "data" / "extracted")
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "mistral-small-latest")
EXTRACTION_MAX_CHARS = int(os.getenv("EXTRACTION_MAX_CHARS", "30000"))
VALIDATION_MAX_CHARS = int(os.getenv("VALIDATION_MAX_CHARS", "20000"))
