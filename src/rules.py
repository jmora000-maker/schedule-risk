"""
Script Name: rules.py
Description: Audits project artifacts to detect schedule-risk patterns.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-28
"""

from datetime import datetime, timedelta, date
from src.inputs import ProjectArtifactLoader
from src.models import RiskFinding, RiskSignal, Issue, TaskUpdate
from typing import List, Optional, Any
from src.graph_manager import GraphManager

# --- PIPELINE LAYER: DETERMINISTIC AUDIT RULES ENGINE ---
STALE_UPDATE_DAYS = 7
HIGH_SEVERITY = {"high", "critical", "red"}
READINESS_KEYWORDS = {"readiness", "go-live", "cutover", "signoff", "deployment"}
VENDOR_KEYWORDS = {"vendor", "external", "supplier", "third party"}

class RuleEngine:
    def __init__(self, context: ProjectArtifactLoader, graph: GraphManager):
        self.context = context
        self.graph = graph
        self.tasks_by_uid = {t.task_uid: t for t in context.tasks if t.task_uid is not None}
        self.tasks_by_id = {t.task_id: t for t in context.tasks if t.task_id is not None}
        self.milestones = context.milestones
        self.issues = context.issues
        self.task_updates = context.task_updates
        self.delivery_notes = context.delivery_notes
        self.signals = context.signals

    def _finding_id(self, rule_name: str, task=None, milestone_id=None) -> str:
        if task and getattr(task, "task_uid", None) is not None:
            return f"{rule_name.upper()}-TASK-{task.task_uid}"
        if milestone_id:
            return f"{rule_name.upper()}-MS-{milestone_id}"
        return f"{rule_name.upper()}-GEN"

    def _make_finding(
        self,
        finding_id: str,
        rule_name: str,
        signal_type: str,
        severity: str,
        confidence: float,
        summary: str,
        evidence: List[str],
        task=None,
        milestone_id=None,
        source_artifact=None,
        metadata=None,
    ) -> RiskFinding:
        resolved_milestone_id = milestone_id
        if resolved_milestone_id is None and task and getattr(task, "is_milestone", False):
            resolved_milestone_id = str(task.task_uid)

        return RiskFinding(
            finding_id=finding_id,
            rule_name=rule_name,
            signal_type=signal_type,
            severity=severity,
            confidence=confidence,
            summary=summary,
            evidence=evidence,
            task_id=getattr(task, "task_id", None),
            task_uid=getattr(task, "task_uid", None),
            milestone_id=resolved_milestone_id,
            source_artifact=source_artifact,
            metadata=metadata or {},
        )

    def _signals_for_task(self, task_uid: int) -> List[RiskSignal]:
        return [s for s in self.signals if s.task_uid == task_uid]

    def _issues_for_task(self, task_uid: int) -> List[Issue]:
        return [i for i in self.issues if i.task_uid == task_uid]

    def _updates_for_task(self, task_uid: int) -> List[TaskUpdate]:
        return [u for u in self.task_updates if u.task_uid == task_uid]

    def run(self) -> List[RiskFinding]:
        all_findings: List[RiskFinding] = []
        all_findings.extend(self.detect_milestone_drift())
        all_findings.extend(self.detect_dependency_delay())
        all_findings.extend(self.detect_vendor_delay())
        all_findings.extend(self.detect_stale_updates())
        all_findings.extend(self.detect_readiness_risk())
        all_findings.extend(self.detect_blocker_accumulation())
        all_findings.extend(self.detect_critical_path_exposure())

        unique_findings = []
        seen = set()
        for f in all_findings:
            key = (f.rule_name, f.task_uid, f.milestone_id)
            if key not in seen:
                seen.add(key)
                unique_findings.append(f)
        
        return unique_findings

    def detect_milestone_drift(self) -> List[RiskFinding]:
        findings = []
        for m in self.milestones:
            if m.task_uid and m.task_uid in self.tasks_by_uid:
                task = self.tasks_by_uid[m.task_uid]
                if task.baseline_finish and task.finish and task.finish > task.baseline_finish:
                    evidence = [f"Baseline finish: {task.baseline_finish}", f"Actual finish: {task.finish}"]
                    confidence = 1.0 if len(evidence) >= 2 else 0.8
                    rule_name = "milestone_drift"
                    findings.append(self._make_finding(
                        self._finding_id(rule_name, task=task, milestone_id=m.milestone_id),
                        rule_name, "schedule_delay", "red", confidence,
                        f"Milestone '{m.name}' has slipped beyond baseline.",
                        evidence,
                        task=task, milestone_id=m.milestone_id
                    ))
        return findings

    def detect_dependency_delay(self) -> List[RiskFinding]:
        findings = []
        for task in self.context.tasks:
            if task.predecessor_uids:
                delayed_preds = []
                for pred_uid in task.predecessor_uids:
                    pred_task = self.tasks_by_uid.get(pred_uid)
                    if pred_task and pred_task.finish and pred_task.baseline_finish and pred_task.finish > pred_task.baseline_finish:
                        delayed_preds.append(pred_task)
                
                if delayed_preds:
                    signals = []
                    for p in delayed_preds:
                        signals.extend(self._signals_for_task(p.task_uid))
                    
                    has_high_severity = any((s.severity or "").lower() in HIGH_SEVERITY for s in signals)
                    severity = "red" if len(delayed_preds) > 1 or has_high_severity else "amber"
                    
                    evidence = [f"Predecessor '{p.name}' is late" for p in delayed_preds]
                    confidence = 1.0 if len(evidence) >= 2 else 0.8
                    
                    rule_name = "dependency_delay"
                    findings.append(self._make_finding(
                        self._finding_id(rule_name, task=task),
                        rule_name, "schedule_delay", severity, confidence,
                        f"Task '{task.name}' is impacted by delayed predecessor(s).",
                        evidence,
                        task=task
                    ))
        return findings

    def detect_vendor_delay(self) -> List[RiskFinding]:
        findings = []
        for task in self.context.tasks:
            notes_text = (task.notes or "").lower()
            name_text = (task.name or "").lower()
            owner_team = (task.owner_team or "").lower()
            slip_category = (task.slip_category or "").lower()

            is_vendor_task = (
                owner_team == "vendor"
                or slip_category == "vendor"
                or any(k in notes_text for k in VENDOR_KEYWORDS)
                or any(k in name_text for k in VENDOR_KEYWORDS)
            )

            if not is_vendor_task or task.task_uid is None:
                continue

            signals = self._signals_for_task(task.task_uid)
            vendor_signals = []
            for s in signals:
                signal_type = (s.signal_type or "").lower()
                evidence_text = " ".join(s.evidence or []).lower() if isinstance(s.evidence, list) else str(s.evidence or "").lower()
                if "vendor" in signal_type or "vendor" in evidence_text:
                    vendor_signals.append(s)

            if vendor_signals:
                evidence = [
                    f"Detected {len(vendor_signals)} vendor-related signal(s)",
                    f"Task slip category: {task.slip_category or 'Not Specified'}"
                ]
                confidence = 1.0 if len(evidence) >= 2 else 0.8
                rule_name = "vendor_delay"
                findings.append(self._make_finding(
                    self._finding_id(rule_name, task=task),
                    rule_name,
                    "vendor_risk",
                    "amber",
                    confidence,
                    f"Vendor task '{task.name}' has vendor-related risk signals.",
                    evidence,
                    task=task
                ))
        return findings

    def detect_stale_updates(self) -> List[RiskFinding]:
        findings = []
        today = date.today()
        for task in self.context.tasks:
            status_text = (task.status or "").lower()
            update_health = (task.update_health or "").lower()
            active_statuses = {"in progress", "critical", "amber", "red", "at risk"}

            if status_text in active_statuses or update_health in {"amber", "red"}:
                updates = self._updates_for_task(task.task_uid)
                latest_update = max((u.event_date for u in updates if u.event_date), default=None)
                is_stale = not latest_update or (today - latest_update).days > STALE_UPDATE_DAYS
                
                if (
                    is_stale
                    or update_health == "red"
                ):
                    severity = "red" if (is_stale and (status_text == "critical" or update_health == "red")) else "amber"
                    evidence = [
                        f"Latest update: {latest_update}",
                        f"Status: {task.status}",
                        f"Update Health: {task.update_health}"
                    ]
                    confidence = 1.0 if len(evidence) >= 2 else 0.8
                    rule_name = "stale_updates"
                    findings.append(self._make_finding(
                        self._finding_id(rule_name, task=task),
                        rule_name, "status_risk", severity, confidence,
                        f"Task '{task.name}' has stale updates or health issues.",
                        evidence,
                        task=task
                    ))
        return findings

    def detect_readiness_risk(self) -> List[RiskFinding]:
        findings = []
        for task in self.context.tasks:
            name_text = (task.name or "").lower()
            if any(k in name_text for k in READINESS_KEYWORDS):
                upstream_chain = self.graph.get_upstream_chain(task.task_uid)
                # Check if any upstream task is delayed
                is_upstream_delayed = False
                for upstream in upstream_chain:
                    if isinstance(upstream, dict):
                        u_uid = upstream.get("task_uid")
                    else:
                        u_uid = upstream
                    u_task = self.tasks_by_uid.get(u_uid)
                    if u_task and u_task.finish and u_task.baseline_finish and u_task.finish > u_task.baseline_finish:
                        is_upstream_delayed = True
                        break
                
                issues = self._issues_for_task(task.task_uid)
                high_issues = [i for i in issues if (i.severity or "").lower() in HIGH_SEVERITY]
                
                if is_upstream_delayed or high_issues:
                    severity = "red" if is_upstream_delayed and high_issues else "amber"
                    evidence = []
                    if is_upstream_delayed: evidence.append("Upstream tasks delayed")
                    if high_issues: evidence.append(f"{len(high_issues)} high severity issues")
                    
                    confidence = 1.0 if len(evidence) >= 2 else 0.8
                    rule_name = "readiness_risk"
                    findings.append(self._make_finding(
                        self._finding_id(rule_name, task=task),
                        rule_name, "readiness_risk", severity, confidence,
                        f"Readiness task '{task.name}' is at risk.",
                        evidence,
                        task=task
                    ))
        return findings

    def detect_blocker_accumulation(self) -> List[RiskFinding]:
        findings = []
        for task in self.context.tasks:
            issues = self._issues_for_task(task.task_uid)
            high_issues = [i for i in issues if (i.severity or "").lower() in HIGH_SEVERITY]
            signals = self._signals_for_task(task.task_uid)
            blocker_signals = [
                s for s in signals
                if any(k in (s.signal_type or "").lower() for k in {"blocker", "rework", "dependency", "vendor", "readiness"})
            ]
            
            if len(high_issues) > 1 or len(blocker_signals) > 1:
                severity = "red" if len(high_issues) > 1 and len(blocker_signals) > 1 else "amber"
                evidence = []
                if len(high_issues) > 1: evidence.append(f"{len(high_issues)} high severity issues")
                if len(blocker_signals) > 1: evidence.append(f"{len(blocker_signals)} blocker signals")
                
                confidence = 1.0 if len(evidence) >= 2 else 0.8
                rule_name = "blocker_accumulation"
                findings.append(self._make_finding(
                    self._finding_id(rule_name, task=task),
                    rule_name, "blocker_risk", severity, confidence,
                    f"Task '{task.name}' has multiple blockers/issues.",
                    evidence,
                    task=task
                ))
        return findings

    def detect_critical_path_exposure(self) -> List[RiskFinding]:
        findings = []
        for task in self.context.tasks:
            if task.critical:
                is_slipped = task.finish and task.baseline_finish and task.finish > task.baseline_finish
                slack_text = str(task.total_slack or "").strip().upper()
                has_zero_slack = slack_text in {"0", "0.0", "PT0H0M0S"}
                
                delayed_preds = []
                for pred_uid in (task.predecessor_uids or []):
                    pred_task = self.tasks_by_uid.get(pred_uid)
                    if pred_task and pred_task.finish and pred_task.baseline_finish and pred_task.finish > pred_task.baseline_finish:
                        delayed_preds.append(pred_task)
                
                if is_slipped or has_zero_slack or delayed_preds:
                    severity = "red" if (is_slipped and has_zero_slack) or len(delayed_preds) > 0 else "amber"
                    evidence = []
                    if is_slipped: evidence.append("Task has slipped")
                    if has_zero_slack: evidence.append("Task has zero slack")
                    if delayed_preds: evidence.append(f"{len(delayed_preds)} delayed predecessors")
                    
                    confidence = 1.0 if len(evidence) >= 2 else 0.8
                    rule_name = "critical_path_exposure"
                    findings.append(self._make_finding(
                        self._finding_id(rule_name, task=task),
                        rule_name, "critical_path_risk", severity, confidence,
                        f"Critical task '{task.name}' is exposed.",
                        evidence,
                        task=task
                    ))
        return findings
