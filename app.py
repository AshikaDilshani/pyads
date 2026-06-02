"""Streamlit web interface for pyads adsorption data extraction.

Provides two modes:
- Extract: paste OCR text and call the Mistral API with a user-supplied key.
- Demo: explore a pre-computed extraction result with no API key required.

Launch with:
    streamlit run app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pyads.extractor import (  # noqa: E402
    _attach_material_confidence,
    extract_data_from_text,
    flatten_record,
    validate_record_from_text,
)

# ---------------------------------------------------------------------------
# Static assets
# ---------------------------------------------------------------------------

_SAMPLE_OCR_PATH = PROJECT_ROOT / "data" / "samples" / "sample_ocr.txt"
_SAMPLE_RECORD_PATH = PROJECT_ROOT / "data" / "samples" / "sample_adsorption_data.json"

_SAMPLE_OCR = _SAMPLE_OCR_PATH.read_text(encoding="utf-8") if _SAMPLE_OCR_PATH.exists() else ""
_SAMPLE_RECORDS = (
    json.loads(_SAMPLE_RECORD_PATH.read_text(encoding="utf-8"))
    if _SAMPLE_RECORD_PATH.exists()
    else []
)
_SAMPLE_RECORD = _SAMPLE_RECORDS[0] if _SAMPLE_RECORDS else {}

_CONFIDENCE_COLOUR = {
    "high": "#27ae60",
    "medium": "#e67e22",
    "low": "#e74c3c",
    "absent": "#95a5a6",
}

_MODELS = [
    "mistral-small-latest",
    "mistral-medium-latest",
    "mistral-large-latest",
]


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _badge(level: str) -> str:
    """Return an HTML confidence badge for *level*."""
    colour = _CONFIDENCE_COLOUR.get(level or "absent", "#95a5a6")
    return (
        f'<span style="background:{colour};color:#fff;padding:1px 7px;'
        f'border-radius:4px;font-size:0.82em;font-weight:600">{level or "absent"}</span>'
    )


def _render_material(mat: dict) -> None:
    """Render one material card: metrics + confidence badges."""
    conf = mat.get("confidence") or {}
    fields = conf.get("fields") or {}
    overall = conf.get("overall") or "absent"

    st.markdown(
        f"##### {mat.get('material') or '—'}  &nbsp; confidence: {_badge(overall)}",
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        sa = mat.get("surface_area") or {}
        val, unit = sa.get("value"), sa.get("unit") or ""
        st.metric("BET surface area", f"{val} {unit}" if val is not None else "—")
        st.markdown(_badge(fields.get("surface_area", "absent")), unsafe_allow_html=True)

    with col2:
        pv = mat.get("pore_volume") or {}
        val, unit = pv.get("value"), pv.get("unit") or ""
        st.metric("Pore volume", f"{val} {unit}" if val is not None else "—")
        st.markdown(_badge(fields.get("pore_volume", "absent")), unsafe_allow_html=True)

    with col3:
        ps = mat.get("pore_size") or {}
        val, unit = ps.get("value"), ps.get("unit") or ""
        st.metric("Pore size", f"{val} {unit}" if val is not None else "—")
        st.markdown(_badge(fields.get("pore_size", "absent")), unsafe_allow_html=True)

    gases = mat.get("gases") or []
    temps = mat.get("isotherm_temperatures") or []
    temp_str = "; ".join(f"{t['value']} {t['unit']}" for t in temps)
    st.write(
        f"**Gases:** {', '.join(gases) or '—'} &nbsp;&nbsp; "
        f"**Isotherm temperatures:** {temp_str or '—'}"
    )
    st.markdown("---")


def _render_paper(paper: dict) -> None:
    """Render a full paper result: header + material cards."""
    st.write(f"**DOI:** {paper.get('doi') or '—'}")
    st.write(f"**Title:** {paper.get('title') or '—'}")
    st.write(f"**Year:** {paper.get('year') or '—'}")
    materials = paper.get("materials") or []
    st.write(f"**Materials found:** {len(materials)}")
    st.markdown("---")
    for mat in materials:
        _render_material(mat)


def _download_row(paper: dict) -> None:
    """Render JSON and CSV download buttons for *paper*."""
    rows = flatten_record(paper)
    df = pd.DataFrame(rows)
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="⬇ Download JSON",
            data=json.dumps([paper], indent=2, ensure_ascii=False),
            file_name="adsorption_data.json",
            mime="application/json",
        )
    with col2:
        st.download_button(
            label="⬇ Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="adsorption_data.csv",
            mime="text/csv",
        )


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="pyads — Adsorption Extractor",
    page_icon="🔬",
    layout="wide",
)

st.title("🔬 pyads — Adsorption Data Extractor")
st.caption(
    "Extract BET surface area, pore volume, pore size, gases, and isotherm temperatures "
    "from porous-material papers (MOFs, COFs, zeolites) using Mistral OCR + LLM."
)

# ── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙ Settings")
    api_key = st.text_input(
        "Mistral API key",
        type="password",
        help="Free tier available at console.mistral.ai — not required for the offline demo.",
    )
    model = st.selectbox("Model", _MODELS)
    second_pass = st.checkbox(
        "Run strict validation pass",
        value=True,
        help="A second LLM call that corrects impossible units (e.g. cm³/g in surface_area). "
             "Recommended — roughly doubles API cost per paper.",
    )
    st.markdown("---")
    st.markdown(
        "**Confidence levels**\n\n"
        + "  ".join(
            f"{_badge(lvl)} {lvl}"
            for lvl in ("high", "medium", "low", "absent")
        ),
        unsafe_allow_html=True,
    )
    st.markdown("---")
    st.caption(
        "high — both passes agreed  \n"
        "medium — second pass added information  \n"
        "low — passes disagreed (check manually)  \n"
        "absent — field not found in paper"
    )

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_extract, tab_demo = st.tabs(["Extract from text", "Offline demo"])


# ── Tab 1: live extraction ───────────────────────────────────────────────────
with tab_extract:
    st.subheader("Paste OCR text from a porous-material paper")
    st.caption(
        "Run `python runner.py --skip-extraction --skip-cif-download --skip-cif-analysis` "
        "first to generate OCR text, then paste it here."
    )

    ocr_text = st.text_area(
        "OCR text",
        height=260,
        placeholder="Paste the full text of a porous-material paper here…",
        label_visibility="collapsed",
    )
    source_name = st.text_input(
        "Source filename",
        value="paper.txt",
        help="Used as the source_file field in the output JSON.",
    )

    if st.button("🔍 Extract adsorption data", type="primary"):
        if not api_key:
            st.error("Enter your Mistral API key in the sidebar to use live extraction.")
        elif not ocr_text.strip():
            st.error("Paste some OCR text first.")
        else:
            try:
                from mistralai import Mistral  # pylint: disable=import-outside-toplevel

                client = Mistral(api_key=api_key)

                with st.spinner("First-pass extraction…"):
                    first_paper, usage1 = extract_data_from_text(
                        ocr_text, source_name, client, model
                    )

                paper = first_paper
                usage = usage1

                if second_pass:
                    with st.spinner("Strict validation pass…"):
                        second_paper, usage2 = validate_record_from_text(
                            first_paper, ocr_text, client, model
                        )
                        paper = _attach_material_confidence(first_paper, second_paper)
                        usage = {
                            k: usage1.get(k, 0) + usage2.get(k, 0)
                            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                        }

                n_materials = len(paper.get("materials") or [])
                st.success(
                    f"Extracted **{n_materials} material(s)**. "
                    f"Tokens used: {usage.get('total_tokens', 0):,}"
                )
                _render_paper(paper)
                _download_row(paper)

            except Exception as exc:  # pylint: disable=broad-exception-caught
                st.error(f"Extraction failed: {exc}")


# ── Tab 2: offline demo ──────────────────────────────────────────────────────
with tab_demo:
    st.subheader("Offline demo — ZIF-8 CO₂/N₂ adsorption")
    st.caption(
        "No API key required. This shows the pre-computed extraction result for a "
        "published ZIF-8 paper (DOI: 10.1039/c3ce40583f)."
    )

    with st.expander("Show OCR text used for this demo"):
        st.text(_SAMPLE_OCR)

    if _SAMPLE_RECORD:
        st.markdown("### Extraction result (schema v2)")
        _render_paper(_SAMPLE_RECORD)

        flat_rows = flatten_record(_SAMPLE_RECORD)
        st.markdown("### Flat table (Excel view)")
        st.dataframe(pd.DataFrame(flat_rows), use_container_width=True)
        _download_row(_SAMPLE_RECORD)
    else:
        st.warning("Sample data not found. Run the pipeline first to generate output.")

    st.markdown("---")
    st.markdown(
        "To run the full pipeline on your own PDFs: "
        "`python runner.py` — then paste the OCR text into the **Extract** tab."
    )
