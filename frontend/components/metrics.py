"""
Dashboard Metrics Component
---------------------------
Renders statistical summary cards from real backend document data.
"""

from typing import Any, Dict, List
import streamlit as st


def render_dashboard_metrics(documents: List[Dict[str, Any]]):
    """
    Renders enterprise KPI cards summarizing inspection statistics.
    
    Args:
        documents: List of document metadata dictionaries from backend list endpoint.
    """
    if not documents:
        st.info("ℹ️ No documents uploaded yet. Upload a document to view analytics.")
        return

    total_docs = len(documents)
    completed_docs = sum(1 for d in documents if d.get("status") == "COMPLETED")
    failed_docs = sum(1 for d in documents if d.get("status") == "FAILED")
    total_findings = sum(d.get("findings_count", 0) for d in documents)

    approved = sum(1 for d in documents if d.get("decision") == "APPROVED")
    rejected = sum(1 for d in documents if d.get("decision") == "REJECTED")
    pending_review = sum(1 for d in documents if d.get("status") == "COMPLETED" and not d.get("has_decision"))

    # Top Row: Processing Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Uploaded", total_docs)
    with col2:
        st.metric("Inspections Completed", completed_docs)
    with col3:
        st.metric("Inspections Failed", failed_docs)
    with col4:
        st.metric("Verified Flags", total_findings)

    # Bottom Row: Human Governance Metrics
    col5, col6, col7 = st.columns(3)
    with col5:
        st.metric("Pending Officer Review", pending_review)
    with col6:
        st.metric("Approved Documents", approved)
    with col7:
        st.metric("Rejected Documents", rejected)

