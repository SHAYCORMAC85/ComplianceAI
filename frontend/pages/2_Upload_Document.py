"""
Upload Document Page
--------------------
Handles document intake for TXT, PDF, and DOCX files.
Submits uploads to POST /api/documents/upload and redirects to findings inspection.
"""

import hashlib
import uuid
from pathlib import Path
import streamlit as st
from frontend.api.client import api_client, APIClientError
from frontend.components.sidebar import render_sidebar
from frontend.config import APP_NAME, MAX_FILE_SIZE_MB, MAX_FILE_SIZE_BYTES, ALLOWED_EXTENSIONS
from frontend.utils.formatting import format_file_size, get_status_badge_html

st.set_page_config(page_title=f"{APP_NAME} - Upload Document", page_icon="📤", layout="wide")
render_sidebar()

st.title("📤 Upload Document for Inspection")
st.caption("Upload financial prospectuses, contracts, marketing communications, or audit reports for automated AI compliance inspection.")

st.caption("PDF inspection uses embedded text. Image content, including scanned pages, requires separate officer review.")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_file = st.file_uploader(
        f"Select Document File (Max {MAX_FILE_SIZE_MB} MB)",
        type=ALLOWED_EXTENSIONS,
        help=f"Supported file formats: TXT, PDF, DOCX. Exact upload size limit: {MAX_FILE_SIZE_MB} MB."
    )

    if uploaded_file is not None:
        provider = st.session_state.get("configured_provider")
        permitted = provider == "mock" or (provider and st.checkbox(
            f"I am authorized to send this document’s target sections and surrounding text to {provider} for inspection.",
            key=f"consent-{provider}-{uploaded_file.file_id}"))
        file_size = len(uploaded_file.getvalue())
        st.write(f"📁 **Filename:** `{uploaded_file.name}` • **Size:** `{format_file_size(file_size)}`")

        # Strict client-side 15 MB limit validation
        if file_size > MAX_FILE_SIZE_BYTES:
            st.error(
                f"❌ File size ({format_file_size(file_size)}) exceeds the maximum allowed upload limit of {MAX_FILE_SIZE_MB} MB. "
                "Please select a smaller file."
            )
        elif file_size == 0:
            st.error("❌ The selected file is empty (0 bytes). Please upload a valid document.")
        else:
            if st.button("🚀 Start Compliance Inspection", disabled=not permitted, type="primary", use_container_width=True):
                with st.spinner("Registering document..."):
                    try:
                        identity = (uploaded_file.name, hashlib.sha256(uploaded_file.getbuffer()).hexdigest())
                        if st.session_state.get("submission_identity") != identity:
                            st.session_state["submission_identity"] = identity
                            st.session_state["submission_key"] = str(uuid.uuid4())
                        result = api_client.upload_document(
                            filename=uploaded_file.name,
                            file_bytes=uploaded_file.getvalue(),
                            provider=provider,
                            submission_key=st.session_state["submission_key"],
                            mime_type=uploaded_file.type
                        )
                        st.session_state["last_upload_result"] = result
                        st.session_state["active_document_id"] = result["document_id"]
                        st.session_state["active_document_name"] = uploaded_file.name
                    except APIClientError as err:
                        st.session_state["last_upload_result"] = None
                        st.error(f"❌ Upload failed: {err.message}")

    try:
        tracked = {row["document_id"]: row for row in api_client.list_documents()}
    except APIClientError as err:
        st.warning(err.message)
        tracked = {}

    if tracked:
        with st.expander("Reopen inspection"):
            selected = st.selectbox("Inspection", list(tracked),
                                    format_func=lambda key: f"{tracked[key]['filename']} ({key})")
            if st.button("Open inspection"):
                st.session_state["active_document_id"] = selected

    doc_id = st.session_state.get("active_document_id")
    if doc_id:
        st.write(f"Document ID: {doc_id}")
        active = tracked.get(doc_id, {}).get("status") in ("QUEUED", "PROCESSING")

        @st.fragment(run_every=2 if active else None)
        def render_status():
            try:
                info = api_client.get_document_status(doc_id)
            except APIClientError as err:
                st.error(err.message)
                return
            state = info["status"]
            if active and state in ("COMPLETED", "FAILED"):
                st.rerun()
            st.write(f"Inspection stage: {info['stage']}")
            if info.get("progress_tracked", True) and info.get("progress_percent") is not None:
                st.progress(info["progress_percent"], text=f"{info['processed_chunks']} of {info['chunks_count']} sections evaluated")
            if info.get("progress_tracked", True):
                st.caption(f"Analyzed {info['analyzed']} · Cached {info['cached']} · Skipped {info['skipped']} · Failed {info['failed']}")
            if info["stage"] == "WAITING_FOR_QUOTA":
                st.info(f"Waiting for provider quota. Next attempt allowed at {info['retry_at']}.")
            if state == "FAILED":
                st.error(info["error_message"] or "Inspection failed.")
                provider = st.session_state.get("configured_provider")
                consent = provider == "mock" or (provider and st.checkbox(
                    f"I authorize sending this inspection’s text to {provider} on retry.", key=f"retry-consent-{provider}-{doc_id}"))
                if not info["has_decision"] and st.button("Retry inspection", disabled=not consent):
                    try:
                        api_client.retry_document(doc_id, provider=provider)
                    except APIClientError as err:
                        st.error(err.message)
                    else:
                        st.rerun()
            elif state == "COMPLETED":
                if info["skipped"]:
                    st.warning("Skipped sections did not receive a model assessment.")
                if st.button("View inspection findings"):
                    st.switch_page("pages/3_Inspection_Findings.py")
        render_status()

with col2:
    st.markdown("### ℹ️ Inspection Pipeline")
    st.markdown(
        """
        1. **Extraction**: Text is extracted natively from TXT, PDF (`PyMuPDF`), or DOCX (`python-docx`).
        2. **Segmentation**: Document is divided into logical paragraph sections.
        3. **Rule Retrieval**: Relevant active regulations are matched via keyword algorithms.
        4. **AI Assessment**: LLM inspects sections against compliance mandates.
        5. **Verbatim Verification**: Every flagged quote is validated against the original text.
        6. **Human Sign-Off**: An authorized compliance officer makes the final determination.
        """
    )
    st.info("Mock inspection runs locally. External inspection sends target text, bounded surrounding text and illustrative rules to the configured provider. Use authorized documents only.")

