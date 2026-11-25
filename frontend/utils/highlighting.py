"""
Document Text Highlighting Utility
----------------------------------
Uses verified character offsets (offset_start, offset_end) to highlight
flagged passages in the original extracted document text.

Features:
- Strict invariant verification: text[start:end] == passage.
- Color-coded highlights matching finding severity.
- Safe handling of multiple and overlapping findings without offset corruption.
- HTML-escapes content to prevent injection or broken formatting.
"""

import html
from typing import Any, Dict, List, Tuple
from frontend.config import SEVERITY_COLORS


def highlight_document_text(
    raw_text: str,
    findings: List[Dict[str, Any]]
) -> Tuple[str, List[str]]:
    """
    Renders raw document text as an HTML block with color-coded highlights for each finding.
    
    Args:
        raw_text: Full, un-modified extracted text string.
        findings: List of verified finding dictionaries containing offset_start, offset_end,
                  passage, rule_id, and severity.
                  
    Returns:
        Tuple of:
        - Rendered HTML string ready for st.markdown(..., unsafe_allow_html=True)
        - List of verification warnings if any offset did not match passage text verbatim.
    """
    if not raw_text:
        return '<div class="compliance-doc-viewer" style="background-color: #FFFFFF !important; color: #475569 !important; border: 1px solid #CBD5E1; border-radius: 6px; padding: 18px;"><em style="color: #475569 !important;">Document text is empty.</em></div>', []

    if not findings:
        escaped_text = html.escape(raw_text)
        return (
            f'<pre class="compliance-doc-viewer" style="background-color: #FFFFFF !important; color: #111827 !important; border: 1px solid #CBD5E1; '
            f'border-radius: 6px; padding: 18px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; '
            f'line-height: 1.6; font-size: 0.9em; max-height: 550px; overflow-y: auto; margin: 0;">'
            f'<span style="color: #111827 !important;">{escaped_text}</span></pre>',
            []
        )

    warnings: List[str] = []
    valid_intervals = []

    # 1. Invariant verification & collection of intervals
    for f in findings:
        start = f.get("offset_start")
        end = f.get("offset_end")
        passage = f.get("passage", "")
        rule_id = f.get("rule_id", "Unknown")
        severity = f.get("severity", "MEDIUM").upper()

        if start is None or end is None:
            warnings.append(f"Finding for rule {rule_id} has missing offsets; highlight skipped.")
            continue

        if start < 0 or end > len(raw_text) or start >= end:
            warnings.append(f"Finding for rule {rule_id} has out-of-bounds offsets [{start}:{end}].")
            continue

        actual_slice = raw_text[start:end]
        if actual_slice != passage:
            warnings.append(
                f"Offset verification warning: raw_text[{start}:{end}] does not match passage for rule {rule_id}."
            )

        valid_intervals.append({
            "start": start,
            "end": end,
            "rule_id": rule_id,
            "severity": severity,
            "passage": passage
        })

    # Sort intervals by start offset ascending, then by end offset descending
    valid_intervals.sort(key=lambda x: (x["start"], -x["end"]))

    # 2. Build non-corrupted highlighted HTML stream
    html_parts: List[str] = []
    current_pos = 0

    for item in valid_intervals:
        start = item["start"]
        end = item["end"]
        sev = item["severity"]
        rule = item["rule_id"]

        # If interval starts before current position (overlap with previous finding)
        if start < current_pos:
            start = current_pos  # Adjust to prevent duplicate text rendering
            if start >= end:
                continue

        # Append un-flagged text prior to this finding
        if start > current_pos:
            unhighlighted = raw_text[current_pos:start]
            html_parts.append(
                f'<span style="color: #111827 !important;">{html.escape(unhighlighted)}</span>'
            )

        # Highlight the passage
        highlighted_slice = raw_text[start:end]
        colors = SEVERITY_COLORS.get(sev, {"bg": "#FEF9C3", "text": "#854D0E", "border": "#FACC15"})

        mark_tag = (
            f'<mark class="highlight-sev-{sev.lower()}" style="background-color: {colors["bg"]} !important; '
            f'color: {colors["text"]} !important; border: 1px solid {colors["border"]} !important; '
            f'border-radius: 3px; padding: 2px 4px; font-weight: 700;" '
            f'title="Violation: {html.escape(rule)} [{sev}]">'
            f'{html.escape(highlighted_slice)}</mark>'
        )
        html_parts.append(mark_tag)
        current_pos = end

    # Append any remaining document text
    if current_pos < len(raw_text):
        remaining = raw_text[current_pos:]
        html_parts.append(
            f'<span style="color: #111827 !important;">{html.escape(remaining)}</span>'
        )

    full_html = "".join(html_parts)
    container_html = (
        f'<pre class="compliance-doc-viewer" style="background-color: #FFFFFF !important; color: #111827 !important; border: 1px solid #CBD5E1; '
        f'border-radius: 6px; padding: 18px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: pre-wrap; '
        f'line-height: 1.6; font-size: 0.9em; max-height: 550px; overflow-y: auto; margin: 0;">'
        f'{full_html}</pre>'
    )

    return container_html, warnings

