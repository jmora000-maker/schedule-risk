"""
Script Name: llm.py
Description: Explanation layer for risk findings and actionable recommendations.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-30
"""

import json
import logging
from typing import List, Dict
from src.config import client
from src.models import RiskFinding, RetrievedEvidenceBundle, RiskExplanation

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You explain an already-detected project schedule risk and recommend the next operational action.

Do not re-diagnose or debate the finding.

Use the supplied finding and evidence to:
1. explain the risk clearly,
2. summarize the strongest supporting evidence,
3. describe likely impact.

Operational Action Rules:
- Return exactly one action.
- Maximum 22 words.
- No bullet points, numbering, or headings.
- Start with a verb.
- Make the action specific to the task, predecessor, milestone, vendor, or readiness condition in the evidence.
- Do not say "accelerate" unless the evidence clearly supports acceleration as the direct remedy.
- Prefer actions like escalate, confirm, rebaseline, unblock, validate, secure, assign, approve, close, or reschedule when appropriate.
- Return plain text only for the action.

Keep the explanation concise, operational, and project-manager friendly."""

def clean_action_text(text: str) -> str:
    fallback = "Validate the latest status and confirm whether the schedule dates still reflect current reality."
    if not text:
        return fallback

    text = " ".join(text.split())
    text = text.replace("- ", "").replace("* ", "")

    if "escalate" in text.lower() and "immediately" in text.lower():
        return fallback

    words = text.split()
    if len(words) > 22:
        text = " ".join(words[:22]).rstrip(",.;:") + "."

    return text

MILESTONE_SUMMARY_PROMPT = """You are a project manager summarizing risks for a specific milestone.
Use the provided list of risk findings to:
1. Summarize the key risks impacting this milestone.
2. Highlight the most urgent issues.
3. Keep the summary operational and concise."""

PORTFOLIO_SUMMARY_PROMPT = """You are a program director summarizing overall project portfolio risks.
Use the provided list of risk findings to:
1. Provide an executive-level summary of the portfolio health.
2. Identify cross-cutting risk themes (e.g., vendor issues, critical path bottlenecks).
3. Recommend top-level priorities for management attention.
Keep the summary concise, actionable, and executive-friendly."""

def build_finding_payload(finding: RiskFinding, evidence: RetrievedEvidenceBundle) -> Dict:
    bundle = evidence.evidence_bundle if evidence and evidence.evidence_bundle else []
    return {
        "finding": finding.model_dump(),
        "evidence": [
            {
                "text": c.text,
                "artifact_type": getattr(c, "artifact_type", None),
                "source_artifact": getattr(c, "source_artifact", None),
                "task_uid": getattr(c, "task_uid", None),
                "task_id": getattr(c, "task_id", None),
                "milestone_id": getattr(c, "milestone_id", None),
            }
            for c in bundle
        ],
        "metadata": {
            "evidence_strength": evidence.evidence_strength if evidence else "weak",
            "source_types": evidence.source_types if evidence else [],
            "is_schedule_only": evidence.is_schedule_only if evidence else False,
        }
    }

def fallback_risk_explanation(finding: RiskFinding, evidence: RetrievedEvidenceBundle) -> str:
    bundle = evidence.evidence_bundle if evidence and evidence.evidence_bundle else []
    top = bundle[:3]
    snippets = " | ".join(c.text[:160] for c in top)
    target = f"task UID {finding.task_uid}" if finding.task_uid else "an unknown task"
    if finding.milestone_id:
        target += f" and milestone {finding.milestone_id}"
    return (
        f"{finding.signal_type} is flagged at {finding.severity} severity affecting {target}. "
        f"The evidence suggests likely schedule impact if not addressed promptly. "
        f"Strongest evidence: {snippets}"
    )

def fallback_next_action(finding: RiskFinding) -> str:
    target = f"task UID {finding.task_uid}" if finding.task_uid else "the affected task"
    if finding.milestone_id:
        return f"Review {target} and milestone {finding.milestone_id} immediately, confirm current dates/dependencies, and assign an owner for corrective action."
    return f"Review {target} immediately, confirm current dates/dependencies, and assign an owner for corrective action."

def generate_risk_explanation(finding: RiskFinding, evidence: RetrievedEvidenceBundle) -> RiskExplanation:
    print(f" -> Generating LLM explanation for finding {finding.finding_id}.")
    payload = build_finding_payload(finding, evidence)
    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Explain this risk finding:\n{json.dumps(payload, indent=2)}"}
            ],
            response_format=RiskExplanation,
            temperature=0.3
        )
        explanation = response.choices[0].message.parsed
        
        # Apply logic for weak evidence
        if evidence.is_schedule_only:
            explanation.recommended_action = "Validate the latest status and confirm whether the schedule dates still reflect current reality."
        
        if explanation.recommended_action:
            explanation.recommended_action = clean_action_text(explanation.recommended_action)
        return explanation
    except Exception as e:
        logger.warning("LLM explanation failed; using fallback: %s", e)
        # Construct a fallback RiskExplanation
        bundle = evidence.evidence_bundle if evidence and evidence.evidence_bundle else []
        top = bundle[:3]
        return RiskExplanation(
            finding_id=finding.finding_id,
            summary=fallback_risk_explanation(finding, evidence),
            impact="Schedule impact likely if not addressed.",
            recommended_action=fallback_next_action(finding),
            evidence_used=[c.text for c in top]
        )

def recommend_next_action(finding: RiskFinding, evidence: RetrievedEvidenceBundle) -> str:
    explanation = generate_risk_explanation(finding, evidence)
    return clean_action_text(explanation.recommended_action)

def generate_milestone_summary(findings: List[RiskFinding]) -> str:
    if not findings:
        return "No risks identified for this milestone."
    payload = [f.model_dump() for f in findings]
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": MILESTONE_SUMMARY_PROMPT},
                {"role": "user", "content": f"Summarize these milestone risks:\n{json.dumps(payload, indent=2)}"}
            ],
            temperature=0.3
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("LLM milestone summary generation failed; using fallback: %s", e)
        return f"Milestone summary: {len(findings)} risks identified, requiring immediate review."

def generate_portfolio_summary(findings: List[RiskFinding]) -> str:
    if not findings:
        return "No risks identified for the portfolio."
    payload = [f.model_dump() for f in findings]
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": PORTFOLIO_SUMMARY_PROMPT},
                {"role": "user", "content": f"Summarize these portfolio risks:\n{json.dumps(payload, indent=2)}"}
            ],
            temperature=0.3
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("LLM portfolio summary generation failed; using fallback: %s", e)
        return f"Portfolio summary: {len(findings)} risks identified, requiring executive attention."
