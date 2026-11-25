"""
Unit Tests for Document Text Highlighting Utility
-------------------------------------------------
Tests character offset verification, multiple findings, overlapping passages,
HTML escaping security, and edge cases (empty text, missing offsets).
"""

from frontend.utils.highlighting import highlight_document_text


def test_highlight_single_finding():
    """Verify highlighting a single verified finding with exact offsets."""
    text = "We offer standard advisory. We promise guaranteed returns with zero risk to all."
    passage = "guaranteed returns with zero risk"
    start = text.find(passage)
    end = start + len(passage)

    findings = [
        {
            "passage": passage,
            "rule_id": "FINRA-2210",
            "severity": "CRITICAL",
            "offset_start": start,
            "offset_end": end
        }
    ]

    html_out, warnings = highlight_document_text(text, findings)

    assert len(warnings) == 0
    assert "<mark" in html_out
    assert passage in html_out
    assert "FINRA-2210" in html_out
    assert "CRITICAL" in html_out


def test_highlight_multiple_non_overlapping_findings():
    """Verify multiple distinct findings are highlighted without corrupting offsets."""
    text = "Clause 1: guaranteed returns. Clause 2: hidden unilateral fee."
    
    p1 = "guaranteed returns"
    s1 = text.find(p1)
    e1 = s1 + len(p1)

    p2 = "hidden unilateral fee"
    s2 = text.find(p2)
    e2 = s2 + len(p2)

    findings = [
        {"passage": p1, "rule_id": "FINRA-2210", "severity": "CRITICAL", "offset_start": s1, "offset_end": e1},
        {"passage": p2, "rule_id": "CFPB-UDAAP", "severity": "HIGH", "offset_start": s2, "offset_end": e2}
    ]

    html_out, warnings = highlight_document_text(text, findings)

    assert len(warnings) == 0
    assert html_out.count("<mark") == 2
    assert "Clause 1:" in html_out
    assert "Clause 2:" in html_out


def test_highlight_overlapping_findings_safely():
    """Ensure overlapping intervals are handled without duplicating or corrupting characters."""
    text = "We promise highly speculative guaranteed returns on stock."
    
    # Overlapping intervals:
    # Finding 1: "highly speculative"
    s1 = text.find("highly speculative")
    e1 = s1 + len("highly speculative")

    # Finding 2: "speculative guaranteed" (overlaps with first)
    s2 = text.find("speculative guaranteed")
    e2 = s2 + len("speculative guaranteed")

    findings = [
        {"passage": "highly speculative", "rule_id": "FINRA-2111", "severity": "HIGH", "offset_start": s1, "offset_end": e1},
        {"passage": "speculative guaranteed", "rule_id": "FINRA-2210", "severity": "CRITICAL", "offset_start": s2, "offset_end": e2}
    ]

    html_out, warnings = highlight_document_text(text, findings)
    assert "<mark" in html_out
    # Text should remain readable and unbroken
    assert "We promise" in html_out
    assert "on stock." in html_out


def test_highlight_offset_mismatch_produces_warning():
    """Verify warning is returned if text at offsets does not match passage verbatim."""
    text = "Original safe document text."
    findings = [
        {
            "passage": "completely different passage",
            "rule_id": "RULE-1",
            "severity": "LOW",
            "offset_start": 0,
            "offset_end": 10
        }
    ]

    html_out, warnings = highlight_document_text(text, findings)
    assert len(warnings) == 1
    assert "does not match passage" in warnings[0]


def test_highlight_html_escaping_prevents_injection():
    """Verify that potentially malicious HTML/JS in document text is properly escaped."""
    malicious_text = "Standard text with <script>alert('xss')</script> and & symbols."
    html_out, _ = highlight_document_text(malicious_text, [])

    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "&amp;" in html_out


def test_highlight_empty_text():
    """Verify graceful handling of empty document text."""
    html_out, warnings = highlight_document_text("", [])
    assert "empty" in html_out.lower()
    assert len(warnings) == 0


def test_highlight_readable_dark_text_styling():
    """Verify unhighlighted text is rendered in high-contrast dark text (#111827) on white paper."""
    raw_text = "Standard compliance clause. Second sentence with flag. Concluding clause."
    findings = [
        {
            "passage": "Second sentence with flag.",
            "rule_id": "TEST-01",
            "severity": "HIGH",
            "offset_start": 28,
            "offset_end": 54
        }
    ]
    html_out, warnings = highlight_document_text(raw_text, findings)
    assert len(warnings) == 0
    assert 'class="compliance-doc-viewer"' in html_out
    assert 'style="color: #111827 !important;"' in html_out
    # Check that normal passages before and after are wrapped in dark text spans
    assert '<span style="color: #111827 !important;">Standard compliance clause. </span>' in html_out
    assert '<span style="color: #111827 !important;"> Concluding clause.</span>' in html_out


def test_highlight_severity_classes_and_distinguishability():
    """Verify that CRITICAL, HIGH, MEDIUM, and LOW highlights receive distinct severity classes."""
    text = "Critical text. High text. Medium text. Low text."
    findings = [
        {"passage": "Critical text.", "rule_id": "R1", "severity": "CRITICAL", "offset_start": 0, "offset_end": 14},
        {"passage": "High text.", "rule_id": "R2", "severity": "HIGH", "offset_start": 15, "offset_end": 25},
        {"passage": "Medium text.", "rule_id": "R3", "severity": "MEDIUM", "offset_start": 26, "offset_end": 38},
        {"passage": "Low text.", "rule_id": "R4", "severity": "LOW", "offset_start": 39, "offset_end": 48},
    ]
    html_out, warnings = highlight_document_text(text, findings)
    assert len(warnings) == 0
    assert 'class="highlight-sev-critical"' in html_out
    assert 'class="highlight-sev-high"' in html_out
    assert 'class="highlight-sev-medium"' in html_out
    assert 'class="highlight-sev-low"' in html_out


def test_highlight_html_escaping_in_flagged_passage():
    """Verify that special characters in flagged passages are escaped to prevent XSS."""
    text = "Notice: <script>alert('bad')</script> & \"quotes\" apply."
    findings = [
        {
            "passage": "<script>alert('bad')</script> & \"quotes\"",
            "rule_id": "SEC-10B5",
            "severity": "CRITICAL",
            "offset_start": 8,
            "offset_end": 48
        }
    ]
    html_out, warnings = highlight_document_text(text, findings)
    assert len(warnings) == 0
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "&amp;" in html_out
    assert "&quot;quotes&quot;" in html_out

