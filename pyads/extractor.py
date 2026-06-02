"""Extract structured adsorption data from OCR text files using Mistral LLM."""

import argparse
import json
import logging
import re
import time
from pathlib import Path

import pandas as pd

try:
    from mistralai import Mistral
except ImportError:
    from mistralai.client import Mistral

from pyads.config import (
    EXTRACTION_DIR,
    EXTRACTION_MAX_CHARS,
    EXTRACTION_MODEL,
    LOG_LEVEL,
    MISTRAL_API_KEY,
    TEXT_DIR,
    VALIDATION_MAX_CHARS,
)
from pyads.confidence import compute_confidence


SCHEMA_TEXT = """
{
  "doi": string or null,
  "title": string or null,
  "year": integer or null,
  "materials": [
    {
      "material": string or null,
      "surface_area": {"value": number or null, "unit": string or null},
      "pore_volume": {"value": number or null, "unit": string or null},
      "pore_size": {"value": number or null, "unit": string or null},
      "gases": [string],
      "isotherm_temperatures": [{"value": number, "unit": string}]
    }
  ]
}
""".strip()


PROMPT_TEMPLATE = """
You are extracting adsorption-material properties from scientific paper OCR text.
Many papers study multiple materials. Extract ALL distinct materials reported.

Return exactly one valid JSON object using this schema:
{{SCHEMA}}

Rules:
- Extract ALL distinct materials mentioned (e.g. both a novel MOF and a reference ZIF-8).
- Use null when a value is not explicitly present in the text.
- Do not guess missing values.
- Treat surface_area as BET surface area only.
- BET surface area must use an area-normalized unit such as m2/g, m^2/g, or m²/g.
- Never put pore volume units such as cm3/g or cm³/g in surface_area.
- Pore volume must use volume-normalized units such as cm3/g or cm³/g.
- Extract all reported isotherm measurement temperatures for each material, not just one.
- Return JSON only. Do not include markdown fences or explanation.

Source file: {{SOURCE_FILE}}

OCR text:
{{TEXT}}
""".strip()


STRICT_VALIDATION_PROMPT = """
You are doing a strict validation pass for multi-material adsorption extraction.

Return exactly one corrected JSON object using this schema:
{{SCHEMA}}

Current extracted JSON:
{{CURRENT_JSON}}

Evidence from OCR text:
{{TEXT}}

Strict correction rules:
- Preserve all materials found; add any missed materials from the evidence.
- Keep DOI, title, year only if supported by the evidence.
- For each material:
  - surface_area is BET surface area only. Valid units: m2/g, m^2/g, m²/g.
    If surface_area has cm3/g, cm³/g, cc/g, nm, Å, K, or °C units, it is wrong.
    Set to null unless a real BET area is present.
  - If a value with cm3/g is a total pore volume, put it in pore_volume.
  - Pore size should use length units such as nm or Å.
  - Extract every isotherm adsorption temperature (e.g. 77 K, 87 K, 195 K, 273 K, 298 K).
  - Do not include synthesis, activation, or catalytic reaction temperatures.
- Do not guess missing values. Use null or empty list when unsupported.
- Return JSON only.
""".strip()


KEYWORD_PATTERN = re.compile(
    r"bet|surface area|specific surface|langmuir|pore volume|micropore|pore size|"
    r"isotherm|adsorption|desorption|77\s*k|87\s*k|195\s*k|273\s*k|298\s*k|temperature",
    re.IGNORECASE,
)


def setup_logging():
    """Configure root logging from the LOG_LEVEL config value."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def _empty_material():
    """Return an empty material entry for schema v2."""
    return {
        "material": None,
        "surface_area": {"value": None, "unit": None},
        "pore_volume": {"value": None, "unit": None},
        "pore_size": {"value": None, "unit": None},
        "gases": [],
        "isotherm_temperatures": [],
    }


def _empty_record(source_file):
    """Return an empty paper record (schema v2) with a materials list."""
    return {
        "schema_version": 2,
        "source_file": source_file,
        "doi": None,
        "title": None,
        "year": None,
        "materials": [],
    }


def _read_text(path, max_chars=None):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if max_chars and len(text) > max_chars:
        return text[:max_chars]
    return text


def _evidence_text(text, max_chars):
    if not max_chars or len(text) <= max_chars:
        return text

    chunks = []
    for paragraph in re.split(r"\n\s*\n", text):
        if KEYWORD_PATTERN.search(paragraph):
            chunks.append(paragraph.strip())
        if sum(len(chunk) for chunk in chunks) >= max_chars:
            break

    evidence = "\n\n".join(chunk for chunk in chunks if chunk)
    if not evidence:
        evidence = text[:max_chars]
    return evidence[:max_chars]


def _message_content(response):
    choice = response.choices[0]
    message = getattr(choice, "message", None)
    if message is None and isinstance(choice, dict):
        message = choice.get("message", {})
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return content or ""


def _usage_dict(response):
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def add_usage(total, usage):
    """Accumulate token counts from *usage* into the *total* dict in place."""
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        total[key] = int(total.get(key) or 0) + int(usage.get(key) or 0)


def _parse_json(content):
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    return json.loads(text)


def _normalize_measure(value, allowed_units=None):
    if not isinstance(value, dict):
        return {"value": None, "unit": None}
    unit = value.get("unit")
    number = value.get("value")
    if number is None or unit is None:
        return {"value": None, "unit": None}
    unit_text = str(unit).lower().replace(" ", "")
    if allowed_units and not any(pattern in unit_text for pattern in allowed_units):
        return {"value": None, "unit": None}
    return {"value": number, "unit": unit}


def _normalize_temperatures(record):
    temps = record.get("isotherm_temperatures")
    if temps is None:
        old_temp = record.get("temperature")
        temps = [old_temp] if isinstance(old_temp, dict) else []
    if isinstance(temps, dict):
        temps = [temps]
    if not isinstance(temps, list):
        return []

    normalized = []
    seen = set()
    for temp in temps:
        if not isinstance(temp, dict):
            continue
        value = temp.get("value")
        unit = temp.get("unit")
        if value is None or unit is None:
            continue
        key = (str(value), str(unit))
        if key not in seen:
            normalized.append({"value": value, "unit": unit})
            seen.add(key)
    return normalized


def _normalize_material(raw):
    """Normalise one material entry from raw LLM output."""
    mat = _empty_material()
    if not isinstance(raw, dict):
        return mat
    mat["material"] = raw.get("material")
    mat["surface_area"] = _normalize_measure(
        raw.get("surface_area"),
        allowed_units=("m2/g", "m^2/g", "m²/g", "sqm/g"),
    )
    mat["pore_volume"] = _normalize_measure(
        raw.get("pore_volume"),
        allowed_units=("cm3/g", "cm^3/g", "cm³/g", "cc/g"),
    )
    mat["pore_size"] = _normalize_measure(raw.get("pore_size"))
    mat["isotherm_temperatures"] = _normalize_temperatures(raw)
    gases = raw.get("gases", [])
    mat["gases"] = [str(gases)] if not isinstance(gases, list) else gases
    return mat


def _normalize_record(raw, source_file):
    """Normalise a raw LLM response into a schema v2 paper record.

    Accepts both the new multi-material format (``materials`` list) and the
    legacy v1 flat format (single material fields at the top level), so the
    pipeline degrades gracefully when the LLM does not follow the new prompt.
    """
    paper = _empty_record(source_file)
    if not isinstance(raw, dict):
        return paper
    for key in ("doi", "title", "year"):
        if key in raw:
            paper[key] = raw[key]
    raw_materials = raw.get("materials")
    if isinstance(raw_materials, list):
        paper["materials"] = [_normalize_material(m) for m in raw_materials if isinstance(m, dict)]
    elif any(k in raw for k in ("material", "surface_area", "gases")):
        # Backward compat: LLM returned a v1-style flat object — wrap it.
        paper["materials"] = [_normalize_material(raw)]
    return paper


def _chat_json(client, model, prompt, system_message):
    response = client.chat.complete(
        model=model,
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return _parse_json(_message_content(response)), _usage_dict(response)


def _is_rate_limit_error(error):
    """Return True for Mistral SDK 429/rate-limit exceptions."""
    text = str(error).lower()
    return "status 429" in text or "rate limit" in text or "rate_limited" in text


def _chat_json_with_retries(client, model, prompt, system_message, retries=2, base_delay=20):
    """Call Mistral with limited retry handling for transient 429 errors."""
    for attempt in range(retries + 1):
        try:
            return _chat_json(client, model, prompt, system_message)
        except Exception as error:  # pylint: disable=broad-exception-caught
            if not _is_rate_limit_error(error) or attempt >= retries:
                raise
            delay = base_delay * (attempt + 1)
            logging.warning("Mistral rate limit hit; retrying in %s seconds.", delay)
            time.sleep(delay)


def extract_data_from_text(text, source_file, client, model):
    """Send OCR text to Mistral and return a normalised paper record (schema v2)."""
    prompt = (
        PROMPT_TEMPLATE
        .replace("{{SCHEMA}}", SCHEMA_TEXT)
        .replace("{{SOURCE_FILE}}", source_file)
        .replace("{{TEXT}}", text)
    )
    raw, usage = _chat_json_with_retries(
        client,
        model,
        prompt,
        "Extract structured adsorption data for all materials and return strict JSON only.",
    )
    return _normalize_record(raw, source_file), usage


def validate_record_from_text(record, text, client, model, max_chars=VALIDATION_MAX_CHARS):
    """Run a strict second-pass correction and return a normalised paper record."""
    source_file = record.get("source_file") or "unknown.txt"
    prompt = (
        STRICT_VALIDATION_PROMPT
        .replace("{{SCHEMA}}", SCHEMA_TEXT)
        .replace("{{CURRENT_JSON}}", json.dumps(record, ensure_ascii=False, indent=2))
        .replace("{{TEXT}}", _evidence_text(text, max_chars))
    )
    corrected, usage = _chat_json_with_retries(
        client,
        model,
        prompt,
        "Validate multi-material adsorption extraction. Correct impossible units. Return strict JSON only.",
    )
    return _normalize_record(corrected, source_file), usage


def _format_temperatures(temperatures):
    return "; ".join(f"{temp.get('value')} {temp.get('unit')}" for temp in temperatures or [])


def flatten_record(paper):
    """Return a list of flat dicts from a v2 paper record, one row per material.

    Each row repeats the paper-level fields (doi, title, year) alongside the
    material-level fields so the Excel output has one complete row per material.
    """
    paper_fields = {
        "source_file": paper.get("source_file"),
        "doi": paper.get("doi"),
        "title": paper.get("title"),
        "year": paper.get("year"),
    }
    materials = paper.get("materials") or []
    if not materials:
        return [{
            **paper_fields,
            "material": None,
            "bet_surface_area_value": None,
            "bet_surface_area_unit": None,
            "pore_volume_value": None,
            "pore_volume_unit": None,
            "pore_size_value": None,
            "pore_size_unit": None,
            "gases": None,
            "isotherm_temperatures": None,
            "confidence_overall": None,
        }]
    rows = []
    for mat in materials:
        row = dict(paper_fields)
        row.update({
            "material": mat.get("material"),
            "bet_surface_area_value": (mat.get("surface_area") or {}).get("value"),
            "bet_surface_area_unit": (mat.get("surface_area") or {}).get("unit"),
            "pore_volume_value": (mat.get("pore_volume") or {}).get("value"),
            "pore_volume_unit": (mat.get("pore_volume") or {}).get("unit"),
            "pore_size_value": (mat.get("pore_size") or {}).get("value"),
            "pore_size_unit": (mat.get("pore_size") or {}).get("unit"),
            "gases": "; ".join(mat.get("gases") or []),
            "isotherm_temperatures": _format_temperatures(mat.get("isotherm_temperatures")),
            "confidence_overall": (mat.get("confidence") or {}).get("overall"),
        })
        rows.append(row)
    return rows


def _attach_material_confidence(first_paper, second_paper):
    """Attach per-material confidence scores to second_paper's materials in place."""
    first_by_name = {
        (m.get("material") or "").lower(): m
        for m in first_paper.get("materials", [])
    }
    for mat in second_paper.get("materials", []):
        name = (mat.get("material") or "").lower()
        first_mat = first_by_name.get(name, _empty_material())
        mat["confidence"] = compute_confidence(first_mat, mat)
    return second_paper


def save_outputs(papers, usage, output_dir):
    """Write papers to JSON/Excel and usage to JSON; return a dict of output paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "adsorption_data.json"
    excel_path = output_dir / "adsorption_data.xlsx"
    usage_path = output_dir / "usage_summary.json"

    json_path.write_text(json.dumps(papers, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = [row for paper in papers for row in flatten_record(paper)]
    pd.DataFrame(rows).to_excel(excel_path, index=False)
    usage_path.write_text(json.dumps(usage, indent=2), encoding="utf-8")

    return {"json": json_path, "excel": excel_path, "usage": usage_path}


def process_text_files(
    text_dir=TEXT_DIR,
    output_dir=EXTRACTION_DIR,
    model=EXTRACTION_MODEL,
    max_chars=EXTRACTION_MAX_CHARS,
    validation_max_chars=VALIDATION_MAX_CHARS,
    limit=None,
    second_pass=True,
):
    """Extract adsorption records from all .txt files in text_dir and save outputs."""
    setup_logging()
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY is not set. Add it to .env or .env.example.")

    text_dir = Path(text_dir)
    text_files = sorted(text_dir.glob("*.txt"))
    if limit:
        text_files = text_files[:limit]
    if not text_files:
        raise FileNotFoundError(f"No .txt files found in {text_dir}")

    client = Mistral(api_key=MISTRAL_API_KEY)
    papers = []
    usage_total = {
        "first_pass": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "second_pass": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    for text_path in text_files:
        logging.info("Extracting structured data from %s", text_path.name)
        full_text = _read_text(text_path)
        first_paper, usage = extract_data_from_text(
            full_text[:max_chars], text_path.name, client, model
        )
        add_usage(usage_total["first_pass"], usage)
        add_usage(usage_total["total"], usage)

        paper = first_paper
        if second_pass:
            logging.info("Running strict validation pass for %s", text_path.name)
            try:
                paper, usage = validate_record_from_text(
                    first_paper, full_text, client, model, validation_max_chars
                )
                add_usage(usage_total["second_pass"], usage)
                add_usage(usage_total["total"], usage)
            except Exception as error:  # pylint: disable=broad-exception-caught
                if not _is_rate_limit_error(error):
                    raise
                logging.warning(
                    "Skipping strict validation for %s due to Mistral rate limit.",
                    text_path.name,
                )

        paper = _attach_material_confidence(first_paper, paper)
        papers.append(paper)

    outputs = save_outputs(papers, usage_total, output_dir)
    return papers, outputs, usage_total


def validate_existing_outputs(
    input_json,
    text_dir=TEXT_DIR,
    output_dir=EXTRACTION_DIR,
    model=EXTRACTION_MODEL,
    validation_max_chars=VALIDATION_MAX_CHARS,
):
    """Re-validate an existing adsorption_data.json with the strict correction pass."""
    setup_logging()
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY is not set. Add it to .env or .env.example.")

    papers = json.loads(Path(input_json).read_text(encoding="utf-8"))
    client = Mistral(api_key=MISTRAL_API_KEY)
    corrected_papers = []
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for paper in papers:
        source_file = paper.get("source_file")
        text_path = Path(text_dir) / source_file
        if not text_path.exists():
            raise FileNotFoundError(f"Missing text file for validation: {text_path}")
        logging.info("Running strict validation pass for %s", source_file)
        text = _read_text(text_path)
        corrected, usage = validate_record_from_text(paper, text, client, model, validation_max_chars)
        corrected_papers.append(corrected)
        add_usage(usage_total, usage)

    outputs = save_outputs(corrected_papers, {"second_pass": usage_total}, output_dir)
    return corrected_papers, outputs, {"second_pass": usage_total}


def _print_usage(usage):
    flat = usage.get("total") or usage.get("second_pass") or usage
    total_tokens = int(flat.get("total_tokens") or 0)
    if total_tokens:
        print(
            "Mistral LLM tokens used: "
            f"{total_tokens} total "
            f"({flat.get('prompt_tokens', 0)} prompt, {flat.get('completion_tokens', 0)} completion)"
        )
    else:
        print("Mistral LLM token usage was not returned by the API.")


def main():
    """CLI entry point for the extraction module."""
    parser = argparse.ArgumentParser(description="Extract structured adsorption data from OCR text files.")
    parser.add_argument("--text-dir", default=str(TEXT_DIR), help="Directory containing OCR .txt files.")
    parser.add_argument("--output-dir", default=str(EXTRACTION_DIR), help="Directory for JSON and Excel outputs.")
    parser.add_argument("--model", default=EXTRACTION_MODEL, help="Mistral chat model for extraction.")
    parser.add_argument(
        "--max-chars", type=int, default=EXTRACTION_MAX_CHARS,
        help="Maximum characters sent per text file.",
    )
    parser.add_argument(
        "--validation-max-chars", type=int, default=VALIDATION_MAX_CHARS,
        help="Maximum evidence characters for validation pass.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N text files.")
    parser.add_argument("--dry-run", action="store_true", help="List files without calling the LLM API.")
    parser.add_argument("--no-second-pass", action="store_true", help="Skip strict validation pass.")
    parser.add_argument(
        "--validate-existing",
        help="Run only the strict validation pass on an existing adsorption_data.json.",
    )
    args = parser.parse_args()

    text_files = sorted(Path(args.text_dir).glob("*.txt"))
    if args.limit:
        text_files = text_files[:args.limit]
    if args.dry_run:
        print(f"Found {len(text_files)} text file(s). No API call made.")
        for text_file in text_files:
            print(text_file)
        return

    if args.validate_existing:
        _, outputs, usage = validate_existing_outputs(
            input_json=args.validate_existing,
            text_dir=args.text_dir,
            output_dir=args.output_dir,
            model=args.model,
            validation_max_chars=args.validation_max_chars,
        )
    else:
        _, outputs, usage = process_text_files(
            text_dir=args.text_dir,
            output_dir=args.output_dir,
            model=args.model,
            max_chars=args.max_chars,
            validation_max_chars=args.validation_max_chars,
            limit=args.limit,
            second_pass=not args.no_second_pass,
        )

    print(f"Saved JSON: {outputs['json']}")
    print(f"Saved Excel: {outputs['excel']}")
    print(f"Saved usage summary: {outputs['usage']}")
    _print_usage(usage)


if __name__ == "__main__":
    main()
