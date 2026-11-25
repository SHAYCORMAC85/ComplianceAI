"""
Sidebar Navigation & System Status Component
--------------------------------------------
Renders consistent branding, backend connectivity health, and current document context.
"""

import streamlit as st
from frontend.api.client import api_client, APIClientError
from frontend.config import APP_NAME, APP_SUBTITLE, APP_ICON, BACKEND_BASE_URL


def render_sidebar():
    """Renders the standard sidebar across all pages."""
    with st.sidebar:
        st.markdown(f"## {APP_ICON} {APP_NAME}")
        st.caption(APP_SUBTITLE)
        st.divider()

        # Backend Health Status Check
        st.markdown("### 🔌 System Status")
        try:
            health = api_client.check_health()
            st.success("API Server: **Online**")
            st.caption(f"Target: `{BACKEND_BASE_URL}`")

            # Dedicated Configured LLM Engine Status Indicator
            provider = str(health.get("llm_provider") or "").lower()
            st.session_state["configured_provider"] = provider


            if provider == "mock":
                st.warning("⚠️ LLM Engine: **MOCK**")
                st.caption(
                    "Simulated compliance rule evaluation. Running in offline zero-cost mode — "
                    "no external AI API calls (OpenAI/Anthropic) are being made."
                )
            else:
                st.info(f"🤖 LLM Engine: **{provider.upper()}**")
                st.caption("Inspection sends text to the configured external provider.")

        except APIClientError as err:
            st.session_state["configured_provider"] = None
            st.error("API Server: **Offline**")
            st.caption(f"Cannot reach `{BACKEND_BASE_URL}`: {err.message}")

        st.divider()

        session = st.session_state.get("officer_session")
        if not session:
            with st.form("officer_sign_in", clear_on_submit=True):
                name = st.text_input("Officer ID")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Sign in"):
                    try:
                        st.session_state["officer_session"] = api_client.sign_in(name.strip(), password)
                    except APIClientError as err:
                        st.error(err.message)
                    else:
                        st.rerun()
            st.stop()
        st.caption(f"Signed in as {session['officer_id']}")
        if st.button("Sign out"):
            try:
                api_client.sign_out(session["token"])
            except APIClientError as err:
                if err.status_code != 401:
                    st.error(err.message)
                    st.stop()
            st.session_state.clear()
            st.rerun()

        # Active Document Context
        active_doc_id = st.session_state.get("active_document_id")
        active_doc_name = st.session_state.get("active_document_name", "None")

        st.markdown("### 📄 Active Document")
        if active_doc_id:
            st.info(f"**{active_doc_name}**\n\n`ID: {active_doc_id[:8]}...`")
            if st.button("Clear Context", use_container_width=True):
                st.session_state["active_document_id"] = None
                st.session_state["active_document_name"] = None
                st.rerun()
        else:
            st.caption("No document currently selected. Upload or inspect a document to set context.")

        st.divider()
        st.caption("ComplianceAI v1.0 • Human-in-the-Loop Governance")

