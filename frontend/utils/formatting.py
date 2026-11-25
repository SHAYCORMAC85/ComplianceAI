"""
UI Formatting Utilities
-----------------------
Helper functions for formatting dates, file sizes, and HTML badges.
"""

from datetime import datetime
import html
from typing import Optional
from frontend.config import SEVERITY_COLORS


def format_timestamp(iso_str: Optional[str]) -> str:
    """Formats an ISO UTC timestamp into a human-readable local string."""
    if not iso_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return iso_str


def format_file_size(size_bytes: int) -> str:
    """Formats byte counts into human-readable KB/MB strings."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def get_severity_badge_html(severity: str) -> str:
    """Renders a styled HTML badge for violation severity."""
    sev_upper = severity.upper()
    colors = SEVERITY_COLORS.get(sev_upper, {"bg": "#EFEFEF", "text": "#333333", "border": "#CCCCCC"})
    return (
        f'<span style="background-color: {colors["bg"]} !important; color: {colors["text"]} !important; '
        f'border: 1px solid {colors["border"]}; border-radius: 4px; padding: 2px 8px; '
        f'font-weight: 700; font-size: 0.85em; display: inline-block;">'
        f'{html.escape(sev_upper)}</span>'
    )


def get_status_badge_html(status: str) -> str:
    """Renders a styled HTML badge for document processing or review status."""
    st_upper = status.upper()
    palette = {
        "COMPLETED": {"bg": "#E6F4EA", "text": "#137333", "border": "#CEEAD6"},
        "APPROVED": {"bg": "#E6F4EA", "text": "#137333", "border": "#CEEAD6"},
        "PROCESSING": {"bg": "#E8F0FE", "text": "#1A73E8", "border": "#D2E3FC"},
        "UPLOADED": {"bg": "#F1F3F4", "text": "#374151", "border": "#DADCE0"},
        "REJECTED": {"bg": "#FCE8E6", "text": "#C5221F", "border": "#FAD2CF"},
        "FAILED": {"bg": "#FCE8E6", "text": "#C5221F", "border": "#FAD2CF"},
        "PENDING": {"bg": "#FEF7E0", "text": "#B06000", "border": "#FEEFC3"},
    }
    colors = palette.get(st_upper, {"bg": "#F1F3F4", "text": "#374151", "border": "#DADCE0"})
    return (
        f'<span style="background-color: {colors["bg"]} !important; color: {colors["text"]} !important; '
        f'border: 1px solid {colors["border"]}; border-radius: 4px; padding: 2px 8px; '
        f'font-weight: 700; font-size: 0.85em; display: inline-block;">'
        f'{html.escape(st_upper)}</span>'
    )

