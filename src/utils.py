"""
Script Name: utils.py
Description: Utility functions for text processing and data parsing.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-28
"""

class StreamlitStdoutRedirector:
    def __init__(self, placeholder, max_chars: int = 8000):
        self.placeholder = placeholder
        self.output_str = ""
        self.max_chars = max_chars

    def reset(self):
        self.output_str = ""
        self.placeholder.empty()

    def write(self, text):
        if not text:
            return
        self.output_str += str(text)
        if len(self.output_str) > self.max_chars:
            self.output_str = self.output_str[-self.max_chars:]
        self.placeholder.code(self.output_str, language="text")

    # Add this exact method to satisfy sys.stdout
    def flush(self):
        pass

def parse_int(val):
    return int(val) if val and str(val).strip().isdigit() else None