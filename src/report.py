"""
Script Name: report.py
Description: Generates and saves structured schedule-risk reports.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-29
"""

from pathlib import Path
from typing import List, Dict, Optional
from src.config import risk_report_path, today
from src.models import RiskFinding, RiskExplanation, RetrievedEvidenceBundle

SEVERITY_ORDER = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}

def normalize_severity(value: str) -> str:
    v = (value or "").lower()
    if v == "red":
        return "critical"
    if v == "amber":
        return "medium"
    return v

def group_findings_by_milestone(findings: List[RiskFinding]) -> Dict[str, List[RiskFinding]]:
    grouped: Dict[str, List[RiskFinding]] = {}
    for f in findings:
        key = str(f.milestone_id) if f.milestone_id is not None else "unmapped"
        grouped.setdefault(key, []).append(f)
    return grouped

def group_findings_by_signal_type(findings: List[RiskFinding]) -> Dict[str, List[RiskFinding]]:
    grouped: Dict[str, List[RiskFinding]] = {}
    for f in findings:
        key = (f.signal_type or "unknown").lower()
        grouped.setdefault(key, []).append(f)
    return grouped

def rank_findings(findings: List[RiskFinding]) -> List[RiskFinding]:
    return sorted(
        findings,
        key=lambda f: (
            -SEVERITY_ORDER.get(normalize_severity(f.severity), 0),
            str(f.milestone_id or ""),
            str(f.task_uid or ""),
            str(f.signal_type or "")
        )
    )

def format_finding_for_ui(
    finding: RiskFinding,
    explanation: Optional[RiskExplanation] = None,
    evidence: Optional[RetrievedEvidenceBundle] = None,
) -> Dict:
    bundle = evidence.evidence_bundle if evidence and evidence.evidence_bundle else []
    top_evidence = bundle[0].text[:240] if bundle else ""

    action_from_llm = bool(
        explanation
        and explanation.recommended_action
        and explanation.recommended_action.strip()
    )

    action = (
        explanation.recommended_action.strip()
        if action_from_llm
        else "Review current dates, dependencies, and owner actions."
    )

    return {
        "finding_id": finding.finding_id,
        "signal_type": finding.signal_type,
        "severity": normalize_severity(finding.severity),
        "target": f"Task UID {finding.task_uid}" if finding.task_uid else f"Milestone {finding.milestone_id}",
        "impact": explanation.impact if explanation and explanation.impact else "",
        "recommended_action": action,
        "action_source": "llm" if action_from_llm else "fallback",
        "top_evidence": top_evidence,
    }

def save_schedule_risk_report(report_text: str, output_path: Path = risk_report_path) -> None:
    output_path.write_text(report_text, encoding="utf-8")

def build_schedule_risk_report(
    findings: List[RiskFinding],
    explanations: Dict[str, RiskExplanation],
    evidence_map: Dict[str, RetrievedEvidenceBundle]
) -> str:
    print(" -> Building schedule risk report.")
    ranked = rank_findings(findings)
    by_milestone = group_findings_by_milestone(ranked)
    by_signal = group_findings_by_signal_type(ranked)

    task_linked = sum(1 for f in findings if f.task_uid is not None)
    milestone_linked = sum(1 for f in findings if f.milestone_id is not None)

    lines = [
        "=" * 80,
        "SCHEDULE RISK REPORT",
        f"Report Date: {today}",
        f"Total Findings: {len(findings)}",
        f"Task-Linked Findings: {task_linked}",
        f"Milestone-Linked Findings: {milestone_linked}",
        "=" * 80,
        "",
        "TOP FINDINGS",
        ""
    ]

    for finding in ranked[:10]:
        exp = explanations.get(finding.finding_id)
        ev = evidence_map.get(finding.finding_id)
        ui = format_finding_for_ui(finding, exp, ev)

        lines.append(f"- [{ui['severity']}] {ui['signal_type']} :: {ui['target']}")
        lines.append(f"  Impact: {ui['impact']}")
        lines.append(f"  Action: {ui['recommended_action']} ({ui['action_source']})")
        if ev:
            lines.append(f"  Evidence Strength: {ev.evidence_strength}")
            lines.append(f"  Evidence Sources: {', '.join(ev.source_types) or 'unknown'}")
            if ev.is_schedule_only:
                lines.append("  Evidence Note: Currently supported by schedule data only.")
        lines.append("")

    lines.append("AT-RISK MILESTONES")
    lines.append("")
    real_milestones = {k: v for k, v in by_milestone.items() if k != "unmapped"}

    if real_milestones:
        for milestone_id, items in real_milestones.items():
            lines.append(f"- Milestone {milestone_id}: {len(items)} findings")
    else:
        lines.append("- No milestone-linked findings identified.")

    unmapped_count = len(by_milestone.get("unmapped", []))
    lines.append("")
    lines.append("UNLINKED FINDINGS")
    lines.append("")
    lines.append(f"- Findings without milestone linkage: {unmapped_count}")

    lines.append("")
    lines.append("FINDINGS BY SIGNAL TYPE")
    lines.append("")
    for signal_type, items in by_signal.items():
        lines.append(f"- {signal_type}: {len(items)}")

    final_report_text = "\n".join(lines)
    save_schedule_risk_report(final_report_text)

    return final_report_text