"""
Findings Display Component
--------------------------
Renders structured cards for strictly verified compliance findings.
"""

import html
from typing import Any, Dict, List
import streamlit as st
from frontend.utils.formatting import get_severity_badge_html, format_timestamp


def render_findings_list(findings: List[Dict[str, Any]]):
    """
    Renders the list of validated compliance findings with severity filters.
    
    Args:
        findings: List of verified finding dictionaries.
    """
    if not findings:
        st.success("✅ **No validated potential risks were flagged.** Officer review is still required.")
        return

    st.markdown(f"### 📋 Verified Findings ({len(findings)})")
    st.caption("Every finding below has been verified verbatim against the source text and linked to a supplied illustrative rule.")

    # Filter Bar
    col1, col2 = st.columns([1, 2])
    with col1:
        severity_filter = st.selectbox(
            "Filter by Severity",
            options=["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"],
            index=0
        )
    with col2:
        search_query = st.text_input("Search Rule ID or Keyword", placeholder="e.g. FINRA-2210, guarantee...").strip().lower()

    # Apply Filters
    filtered = findings
    if severity_filter != "ALL":
        filtered = [f for f in filtered if f.get("severity", "").upper() == severity_filter]

    if search_query:
        filtered = [
            f for f in filtered
            if search_query in f.get("rule_id", "").lower()
            or search_query in f.get("reason", "").lower()
            or search_query in f.get("passage", "").lower()
        ]

    st.markdown(f"**Showing {len(filtered)} of {len(findings)} findings**")

    # Display Findings Cards
    for i, finding in enumerate(filtered, start=1):
        rule_id = finding.get("rule_id", "Unknown")
        severity = finding.get("severity", "MEDIUM")
        passage = finding.get("passage", "")
        reason = finding.get("reason", "")
        offset_start = finding.get("offset_start", 0)
        offset_end = finding.get("offset_end", 0)
        chunk_idx = finding.get("chunk_index", "N/A")
        found_at = format_timestamp(finding.get("found_at"))

        badge_html = get_severity_badge_html(severity)

        with st.container(border=True):
            col_f1, col_f2 = st.columns([3, 1])
            with col_f1:
                st.markdown(f"#### Finding #{i}: `{rule_id}`")
            with col_f2:
                st.markdown(badge_html, unsafe_allow_html=True)

            st.caption("VERBATIM FLAGGED PASSAGE")
            st.markdown(
                f'<div style="background-color: rgba(239, 68, 68, 0.12); '
                f'border-left: 4px solid #EF4444; border-radius: 4px; padding: 10px 14px; '
                f'font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.95em; '
                f'line-height: 1.5; font-weight: 500; margin: 4px 0 10px 0; color: inherit;">'
                f'"{html.escape(passage)}"</div>',
                unsafe_allow_html=True
            )

            st.caption("COMPLIANCE RATIONALE")
            st.text(reason)

            st.caption(f"📍 **Offsets:** [{offset_start}:{offset_end}]  •  📑 **Chunk:** #{chunk_idx}  •  🕒 **Logged:** {found_at}")

