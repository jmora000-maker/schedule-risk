
"""
Script Name: config.py
Description: Project configuration and environment setup.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-28
"""

import os
from datetime import date
from pathlib import Path
from openai import OpenAI

# --- PATH & ENVIRONMENT SETUP ---
today_obj = date.today()
today = today_obj.strftime("%B %d, %Y")

src_folder = Path(__file__).resolve().parent
root_folder = src_folder.parent
data_folder = root_folder / "data"
vector_store_folder = root_folder / "vector_store"
output_folder = root_folder / "outputs"

# --- Hardcoding files for demo ---
meeting_notes_path = data_folder / "meeting_notes_v3.docx"
schedule_path = data_folder / "compact_schedule.xml"
task_updates_path = data_folder / "task_updates.csv"
issue_log_path = data_folder / "issue_log.csv"
delivery_notes_path = data_folder / "delivery_notes.md"
milestones_path = data_folder / "milestones.csv"

folder_paths = [data_folder, vector_store_folder, output_folder]
for folder in folder_paths:
    folder.mkdir(parents=True, exist_ok=True)

risk_report_path = output_folder / "SCHEDULE_RISK_REPORT.txt"
database_file_destination = vector_store_folder / "global_vector_store.json"


# --- INITIALIZE OPENAI CLIENT ---
api_key = os.environ.get("OPENAI_API_KEY", "mock-key-for-local-ui-safety")
is_vector_search_enabled = os.environ.get("OPENAI_API_KEY") is not None and os.environ.get(
    "OPENAI_API_KEY") != "mock-key-for-local-ui-safety"
client = OpenAI(api_key=api_key)