"""
Script Name: app.py
Description: Streamlit dashboard for schedule-risk analysis.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-28
"""

import streamlit as st
import contextlib
from src.config import data_folder, meeting_notes_path
from main import run_automated_pipeline
from src.utils import StreamlitStdoutRedirector


# --- STREAMLIT DASHBOARD INTERFACE ---
st.set_page_config(page_title="AI Schedule Risk Detection", layout="wide")
st.title("Schedule Risk Dashboard")
st.caption("Real-time Schedule Risk Analysis with AI")
st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    st.subheader("System Configuration")

    # --- 2. Hardcoded File Loading Logic ---
    # Check if the data folder exists
    if data_folder.exists():

        st.text(f"Files found in '{data_folder.name}'")
        # iterdir() yields Path objects; we grab .name for just the filename
        files = [f.name for f in data_folder.iterdir()]
        st.write(files)

    else:
        st.error(f"Data directory '{data_folder}' does not exist. Please create it and add your files.")

    start_pipeline = st.button("Execute Schedule Risk Pipeline", use_container_width=True, type="primary")

    st.subheader("Pipeline Summary")
    console_logs = st.empty()
    console_logs.info("Click 'Execute Schedule Risk Pipeline' button to begin.")

with col2:
    st.subheader("Report Workspace")
    report_placeholder = st.empty()
    report_placeholder.info("The Schedule Slip Report will populate here upon synthesis.")

    if start_pipeline:
        console_logs.empty()
        redirector = StreamlitStdoutRedirector(console_logs)
        redirector.reset()

        with st.spinner("Processing Schedule Risk Pipeline..."):
            with contextlib.redirect_stdout(redirector):
                final_narrative = run_automated_pipeline()

        if final_narrative:
            with report_placeholder.container():
                st.html(
                    f"""
                                <div style="
                                    background-color: #1e293b; 
                                    color: #f8fafc; 
                                    padding: 20px; 
                                    border-radius: 8px; 
                                    height: 550px; 
                                    overflow-y: scroll; 
                                    white-space: pre-wrap; 
                                    font-family: inherit;
                                    border: 1px solid #334155;
                                    line-height: 1.5;
                                ">
                                    <p style="font-size: 16px !important; margin: 0; padding: 0;">{final_narrative}</p>
                                </div>
                                """
                )

                st.download_button(
                    label="Download Schedule Risk Report (.txt)",
                    data=final_narrative,
                    file_name="SCHEDULE_RISK_REPORT.txt",
                    mime="text/plain",
                    use_container_width=True
                )