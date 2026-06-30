# AI Schedule Risk Detection

This project provides a real-time, AI-powered dashboard for analyzing schedule risks.

## Features

*   **Automated Risk Pipeline**: Analyzes project schedules and identifies potential risks.
*   **Interactive Dashboard**: A user-friendly Streamlit interface to manage system configuration and run analyses.
*   **Report Generation**: Generates comprehensive schedule risk reports that can be downloaded as text files.

## Setup

1. Clone this repository.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   streamlit run app.py
   ```

## Project Structure

*   `app.py`: The main Streamlit dashboard application.
*   `main.py`: The entry point for the automated risk pipeline.
*   `src/`: Contains core logic, configuration, and utility functions.
*   `data/`: Directory for storing input data files.
*   `outputs/`: Directory for generated reports.
*   `Dockerfile`: Configuration for containerizing the application.
