"""
Script Name: taxonomy.py
Description: Normalizes project concerns into structured risk signals based on a corporate taxonomy.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-30
"""

import re
from typing import Dict, Any, List, Optional
from src.models import RiskSignal
from src.utils import parse_int

# --- CORPORATE TAXONOMY NORMALIZER ---
# This class implements a simple taxonomy-based approach to normalize project concerns into structured risk signals.
# It uses a predefined set of triggers to categorize concerns and assign appropriate severity and confidence levels.
# The taxonomy categories and triggers are designed to capture common project risks and their associated signals.
class CorporateTaxonomyNormalizer:
    def __init__(self):
        # New taxonomy categories and triggers
        self.concern_taxonomy = {
            "dependency_delay": ["dependency delay", "blocked by"],
            "milestone_drift": ["milestone at risk", "target date at risk", "milestone delayed"],
            "vendor_delay": ["vendor delay", "delayed vendor"],
            "rework_signal": ["rework required", "defect backlog increasing"],
            "blocker_accumulation": ["approval stalled", "action item slipped", "stalled", "approval pending"],
            "critical_path_exposure": ["critical path impact"],
            "stale_updates": ["update stale", "no progress"],
        }

    def classify_concern(self, text: str, task_id: Optional[int] = None, task_uid: Optional[int] = None, milestone_id: Optional[str] = None, source_artifact: Optional[str] = None) -> RiskSignal:
        lowered = text.lower()
        
        # Default signal
        signal = RiskSignal(
            signal_type="general_operational_friction",
            severity="medium",
            confidence=0.5,
            evidence=text.strip(),
            task_id=task_id,
            task_uid=task_uid,
            milestone_id=milestone_id,
            source_artifact=source_artifact
        )

        # Check all triggers in taxonomy
        for category, triggers in self.concern_taxonomy.items():
            if any(trigger in lowered for trigger in triggers):
                signal.signal_type = category
                signal.severity = self._infer_severity(lowered)
                signal.confidence = self._infer_confidence(lowered, triggers)
                break
        
        return signal

    def _infer_severity(self, text: str) -> str:
        if any(w in text for w in ["blockage", "critical", "stalled", "vulnerability"]):
            return "critical"
        if any(w in text for w in ["risk", "concern", "delay"]):
            return "high"
        return "medium"

    def _infer_confidence(self, text: str, triggers: List[str]) -> float:
        # Simple heuristic: more triggers, higher confidence
        return min(0.95, 0.5 + (0.1 * len([t for t in triggers if t in text])))
