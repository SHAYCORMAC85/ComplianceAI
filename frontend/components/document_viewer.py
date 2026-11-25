"""
Document Viewer Component
-------------------------
Displays original extracted document text with verified color-coded highlights
identifying flagged passages.
"""

from typing import Any, Dict, List
import streamlit as st
from frontend.config import SEVERITY_COLORS
from frontend.utils.highlighting import highlight_document_text


def render_document_viewer(
    raw_text: str,
    findings: List[Dict[str, Any]],
    filename: str = "document.txt"
):
    """
    Renders the extracted document text with precise character offset highlights.
    
    Args:
        raw_text: Original un-modified document text string.
        findings: List of verified finding dictionaries.
        filename: Name of the active document.
    """
    st.markdown("### 📖 Document Text Inspection")
    st.caption(f"File: **{filename}** • Length: **{len(raw_text):,} characters**")

    # Legend Bar
    legend_cols = st.columns([1, 1, 1, 1])
    for idx, (sev, colors) in enumerate(SEVERITY_COLORS.items()):
        with legend_cols[idx]:
            st.markdown(
                f'<div style="background-color: {colors["bg"]} !important; color: {colors["text"]} !important; '
                f'border: 1px solid {colors["border"]}; border-radius: 4px; padding: 4px 6px; '
                f'text-align: center; font-size: 0.8em; font-weight: 700;">'
                f'■ {sev}</div>',
                unsafe_allow_html=True
            )

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # Scoped styling to ensure document paper viewer maintains crisp dark font in Dark Mode
    st.markdown(
        """
        <style>
        .compliance-doc-viewer,
        pre.compliance-doc-viewer {
            background-color: #FFFFFF !important;
            color: #0F172A !important;
        }
        .compliance-doc-viewer, 
        .compliance-doc-viewer span, 
        .compliance-doc-viewer div,
        .compliance-doc-viewer p,
        pre.compliance-doc-viewer,
        pre.compliance-doc-viewer span,
        pre.compliance-doc-viewer div,
        pre.compliance-doc-viewer p {
            color: #0F172A !important;
            font-weight: 500 !important;
        }
        .compliance-doc-viewer mark,
        pre.compliance-doc-viewer mark {
            font-weight: 700 !important;
        }
        .compliance-doc-viewer mark.highlight-sev-critical,
        pre.compliance-doc-viewer mark.highlight-sev-critical {
            background-color: #FEE2E2 !important;
            color: #991B1B !important;
            border: 1px solid #F87171 !important;
        }
        .compliance-doc-viewer mark.highlight-sev-high,
        pre.compliance-doc-viewer mark.highlight-sev-high {
            background-color: #FFEDD5 !important;
            color: #9A3412 !important;
            border: 1px solid #FB923C !important;
        }
        .compliance-doc-viewer mark.highlight-sev-medium,
        pre.compliance-doc-viewer mark.highlight-sev-medium {
            background-color: #FEF9C3 !important;
            color: #854D0E !important;
            border: 1px solid #FACC15 !important;
        }
        .compliance-doc-viewer mark.highlight-sev-low,
        pre.compliance-doc-viewer mark.highlight-sev-low {
            background-color: #E0F2FE !important;
            color: #075985 !important;
            border: 1px solid #38BDF8 !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Render Highlighted Stream
    rendered_html, warnings = highlight_document_text(raw_text, findings)

    if warnings:
        for w in warnings:
            st.warning(f"⚠️ {w}")

    st.markdown(rendered_html, unsafe_allow_html=True)

