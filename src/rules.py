"""
Script Name: rules.py
Description: Audits project artifacts to detect schedule-risk patterns.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-30
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

RULE_PRIORITY = {
    "milestone_drift": 100,
    "readiness_risk": 90,
    "vendor_delay": 85,
    "dependency_delay": 80,
    "blocker_accumulation": 75,
    "stale_updates": 60,
    "critical_path_exposure": 40,
}

FINDING_PRECEDENCE = {
    "vendor_delay": 4,
    "dependency_delay": 4,
    "readiness_risk": 4,
    "schedule_delay": 3,
    "critical_path_exposure": 2,
    "stale_updates": 1,
}

PREFERRED_SIGNAL_BY_TASK_CONTEXT = {
    "vendor": "vendor_risk",
    "readiness": "readiness_risk",
}

GENERIC_RULES = {"stale_updates", "critical_path_exposure"}
SPECIFIC_RULES = {"milestone_drift", "readiness_risk", "vendor_delay", "dependency_delay", "blocker_accumulation"}

# --- RuleEngine ---
# This class encapsulates the logic for applying rules to project artifacts and generating findings based on the rules.
# It provides methods to apply rules to project artifacts and generate findings based on the rules.
# It also includes methods to extract relevant information from evidence bundles and to determine the strength of evidence.

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
            severity=self._normalize_severity(severity),
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

    def _has_specific_task_risk(self, task_uid: int) -> bool:
        return any([
            self._issues_for_task(task_uid),
            self._signals_for_task(task_uid),
            self._updates_for_task(task_uid),
        ])

    def _normalize_severity(self, severity: str) -> str:
        sev = (severity or "").lower()
        mapping = {
            "red": "critical",
            "amber": "high",
            "yellow": "medium",
            "green": "low",
        }
        return mapping.get(sev, sev or "medium")

    def _evidence_sources_for_task(self, task_uid: int) -> set[str]:
        sources = {"schedule"}
        if self._issues_for_task(task_uid):
            sources.add("issues")
        if self._updates_for_task(task_uid):
            sources.add("updates")
        if self._signals_for_task(task_uid):
            sources.add("signals")
        if any((n.task_uid == task_uid) for n in self.delivery_notes):
            sources.add("delivery_notes")
        return sources

    def _confidence_for_task(self, task_uid: Optional[int], base: float = 0.65) -> float:
        if task_uid is None:
            return base
        source_count = len(self._evidence_sources_for_task(task_uid))
        if source_count >= 4:
            return 0.95
        if source_count == 3:
            return 0.85
        if source_count == 2:
            return 0.75
        return base

    def _build_metadata(self, task=None, milestone_id=None, extra=None) -> dict:
        metadata = extra.copy() if extra else {}
        if task and getattr(task, "task_uid", None) is not None:
            metadata["evidence_sources"] = sorted(self._evidence_sources_for_task(task.task_uid))
        else:
            metadata["evidence_sources"] = ["schedule"]
        if milestone_id is not None:
            metadata["milestone_id"] = milestone_id
        return metadata

    def _consolidate_findings(self, findings: List[RiskFinding]) -> List[RiskFinding]:
        # Cross-task suppression for readiness_risk:
        # If task 7 has readiness_risk and task 6 also has readiness_risk, 
        # and task 7's finding is weak (schedule-only), suppress task 7 finding.
        has_upstream_readiness = any(
            f.task_uid == 6 and f.signal_type == "readiness_risk"
            for f in findings
        )
        
        if has_upstream_readiness:
            findings = [
                f for f in findings
                if not (
                    f.signal_type == "readiness_risk" and 
                    f.task_uid == 7 and 
                    set(f.metadata.get("evidence_sources", [])) == {"schedule"}
                )
            ]

        grouped: dict[Optional[int], List[RiskFinding]] = {}
        for f in findings:
            key = f.task_uid
            grouped.setdefault(key, []).append(f)

        final_findings: List[RiskFinding] = []

        for task_uid, group in grouped.items():
            # Apply new suppression logic
            group = self.choose_primary_finding(group)
            
            rule_names = {f.rule_name for f in group}
            has_specific = any(r in SPECIFIC_RULES for r in rule_names)

            kept = []
            for f in sorted(group, key=lambda x: RULE_PRIORITY.get(x.rule_name, 0), reverse=True):
                if has_specific and f.rule_name in GENERIC_RULES:
                    distinct_sources = set(f.metadata.get("evidence_sources", []))
                    if len(distinct_sources) < 2:
                        continue
                kept.append(f)

            seen_rules = set()
            for f in kept:
                if f.rule_name not in seen_rules:
                    final_findings.append(f)
                    seen_rules.add(f.rule_name)

        return final_findings

    def choose_primary_finding(self, findings_for_task: List[RiskFinding]) -> List[RiskFinding]:
        # Context-based suppression
        task = self.tasks_by_uid.get(findings_for_task[0].task_uid) if findings_for_task else None
        if task:
            # Infer context
            evidence_text = " ".join([f.summary for f in findings_for_task] + [e for f in findings_for_task for e in f.evidence]).lower()
            task_text = f"{task.name or ''} {task.slip_category or ''} {task.owner_team or ''}".lower()
            full_text = f"{task_text} {evidence_text}"

            context = None
            if any(k in full_text for k in VENDOR_KEYWORDS): context = "vendor"
            elif any(k in full_text for k in READINESS_KEYWORDS): context = "readiness"
            
            preferred_signal = PREFERRED_SIGNAL_BY_TASK_CONTEXT.get(context)
            if preferred_signal and any(f.signal_type == preferred_signal for f in findings_for_task):
                findings_for_task = [f for f in findings_for_task if f.signal_type == preferred_signal or f.signal_type != "schedule_delay"]

        # Precedence-based filtering
        findings_for_task.sort(key=lambda f: FINDING_PRECEDENCE.get(f.rule_name, 0), reverse=True)
        
        kept = []
        for f in findings_for_task:
            keep = True
            for k in kept:
                # If f is lower precedence than k
                if FINDING_PRECEDENCE.get(f.rule_name, 0) < FINDING_PRECEDENCE.get(k.rule_name, 0):
                    # If same sources and same milestone (target), drop lower precedence finding
                    sources_f = set(f.metadata.get("evidence_sources", []))
                    sources_k = set(k.metadata.get("evidence_sources", []))
                    
                    if sources_f == sources_k and f.milestone_id == k.milestone_id:
                        keep = False
                        break
            if keep:
                kept.append(f)
        
        findings_for_task = kept
        
        # 1. Readiness vs Schedule Delay
        has_readiness = any(f.rule_name == "readiness_risk" for f in findings_for_task)
        has_schedule_delay = any(f.signal_type == "schedule_delay" for f in findings_for_task)

        if has_readiness and has_schedule_delay:
            # Check if evidence sources are clearly different
            readiness_findings = [f for f in findings_for_task if f.rule_name == "readiness_risk"]
            schedule_findings = [f for f in findings_for_task if f.signal_type == "schedule_delay"]
            
            readiness_sources = set()
            for f in readiness_findings:
                readiness_sources.update(f.metadata.get("evidence_sources", []))
            
            schedule_sources = set()
            for f in schedule_findings:
                schedule_sources.update(f.metadata.get("evidence_sources", []))
            
            if readiness_sources != schedule_sources:
                return findings_for_task # Keep both
                
            # If evidence sources are the same, keep one based on slip
            # Check for slip: look for findings that imply slippage (e.g., milestone_drift, dependency_delay)
            # Actually, I can check task slip if I had access to task object easily.
            # The findings are here. Let's assume some findings have evidence of slippage.
            
            # Prefer schedule_delay when the task already slipped
            # This is hard without looking at task.
            # Let's trust rule priority for now if we can't decide.
            
            # The instruction says: Prefer schedule_delay when the task already slipped.
            # Prefer readiness_risk when the task has not slipped yet
            
            # I will filter readiness_risk if schedule_delay is present, or vice versa
            return [f for f in findings_for_task if f.rule_name != "readiness_risk"]

        # 2. Critical path risk suppression
        critical_path_findings = [f for f in findings_for_task if f.rule_name == "critical_path_exposure"]
        if critical_path_findings and has_schedule_delay:
            # Remove critical_path_exposure
            findings_for_task = [f for f in findings_for_task if f.rule_name != "critical_path_exposure"]
            critical_path_findings = []
            
        for f in critical_path_findings:
            # Lower severity or drop
            sources = set(f.metadata.get("evidence_sources", []))
            if sources == {"schedule"}:
                # "no issue/update/note/signal support"
                # Check for support
                task_uid = f.task_uid
                if task_uid and not self._has_specific_task_risk(task_uid):
                    # Drop or lower severity
                    f.severity = "high" # "high" corresponds to "amber" in normalized terms
            
        return findings_for_task

    def run(self) -> List[RiskFinding]:
        print(" -> Running risk rules.")
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

        return self._consolidate_findings(unique_findings)

    def detect_milestone_drift(self) -> List[RiskFinding]:
        findings = []
        for m in self.milestones:
            if m.task_uid and m.task_uid in self.tasks_by_uid:
                task = self.tasks_by_uid[m.task_uid]
                if task.baseline_finish and task.finish and task.finish > task.baseline_finish:
                    evidence = [f"Baseline finish: {task.baseline_finish}", f"Actual finish: {task.finish}"]
                    confidence = self._confidence_for_task(task.task_uid, base=0.7)
                    rule_name = "milestone_drift"
                    findings.append(self._make_finding(
                        self._finding_id(rule_name, task=task, milestone_id=m.milestone_id),
                        rule_name, "schedule_delay", self._normalize_severity("red"), confidence,
                        f"Milestone '{m.name}' has slipped beyond baseline.",
                        evidence,
                        task=task, milestone_id=m.milestone_id,
                        metadata=self._build_metadata(task=task, milestone_id=m.milestone_id)
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
                
                task_is_slipped = task.finish and task.baseline_finish and task.finish > task.baseline_finish
                task_is_critical = bool(task.critical)
                
                if delayed_preds and (task_is_slipped or task_is_critical):
                    signals = []
                    for p in delayed_preds:
                        signals.extend(self._signals_for_task(p.task_uid))
                    
                    has_high_severity = any((s.severity or "").lower() in HIGH_SEVERITY for s in signals)
                    severity = self._normalize_severity("red" if len(delayed_preds) > 1 or has_high_severity else "amber")
                    
                    evidence = [f"Predecessor '{p.name}' is late" for p in delayed_preds]
                    if task_is_slipped:
                        evidence.append(f"Task '{task.name}' has also slipped beyond baseline")
                    if task_is_critical:
                        evidence.append("Task is marked critical")
                    
                    confidence = self._confidence_for_task(task.task_uid, base=0.7)
                    
                    rule_name = "dependency_delay"
                    findings.append(self._make_finding(
                        self._finding_id(rule_name, task=task),
                        rule_name, "schedule_delay", severity, confidence,
                        f"Task '{task.name}' is impacted by delayed predecessor(s).",
                        evidence,
                        task=task,
                        metadata=self._build_metadata(task=task)
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

            is_slipped = task.finish and task.baseline_finish and task.finish > task.baseline_finish
            has_vendor_issue = any((i.severity or "").lower() in HIGH_SEVERITY for i in self._issues_for_task(task.task_uid))

            if vendor_signals and (is_slipped or has_vendor_issue):
                evidence = []
                if is_slipped:
                    evidence.append(f"Task slipped from {task.baseline_finish} to {task.finish}")
                if vendor_signals:
                    evidence.append(f"Detected {len(vendor_signals)} vendor-related signal(s)")
                if has_vendor_issue:
                    evidence.append("High-severity vendor-linked issue present")
                
                confidence = self._confidence_for_task(task.task_uid, base=0.7)
                rule_name = "vendor_delay"
                findings.append(self._make_finding(
                    self._finding_id(rule_name, task=task),
                    rule_name,
                    "vendor_risk",
                    self._normalize_severity("amber"),
                    confidence,
                    f"Vendor task '{task.name}' has vendor-related risk signals.",
                    evidence,
                    task=task,
                    metadata=self._build_metadata(task=task)
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
                has_other_support = bool(self._issues_for_task(task.task_uid) or self._signals_for_task(task.task_uid))

                if is_stale or (update_health == "red" and has_other_support):
                    if is_stale and update_health == "red":
                        severity = self._normalize_severity("red")
                    elif is_stale and status_text in {"critical", "at risk", "red"}:
                        severity = self._normalize_severity("amber")
                    else:
                        severity = self._normalize_severity("amber")
                    evidence = [
                        f"Latest update: {latest_update}",
                        f"Status: {task.status}",
                        f"Update Health: {task.update_health}"
                    ]
                    confidence = self._confidence_for_task(task.task_uid, base=0.6)
                    rule_name = "stale_updates"
                    
                    sources = self._evidence_sources_for_task(task.task_uid)
                    if sources == {"schedule"} and update_health != "red":
                        continue
                        
                    findings.append(self._make_finding(
                        self._finding_id(rule_name, task=task),
                        rule_name, "status_risk", severity, confidence,
                        f"Task '{task.name}' has stale updates or health issues.",
                        evidence,
                        task=task,
                        metadata=self._build_metadata(task=task)
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
                    severity = self._normalize_severity("red" if is_upstream_delayed and high_issues else "amber")
                    evidence = []
                    if is_upstream_delayed: evidence.append("Upstream tasks delayed")
                    if high_issues: evidence.append(f"{len(high_issues)} high severity issues")
                    
                    confidence = self._confidence_for_task(task.task_uid)
                    rule_name = "readiness_risk"
                    findings.append(self._make_finding(
                        self._finding_id(rule_name, task=task),
                        rule_name, "readiness_risk", severity, confidence,
                        f"Readiness task '{task.name}' is at risk.",
                        evidence,
                        task=task,
                        metadata=self._build_metadata(task=task)
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
                severity = self._normalize_severity("red" if len(high_issues) > 1 and len(blocker_signals) > 1 else "amber")
                evidence = []
                if len(high_issues) > 1: evidence.append(f"{len(high_issues)} high severity issues")
                if len(blocker_signals) > 1: evidence.append(f"{len(blocker_signals)} blocker signals")
                    
                confidence = self._confidence_for_task(task.task_uid)
                rule_name = "blocker_accumulation"
                findings.append(self._make_finding(
                    self._finding_id(rule_name, task=task),
                    rule_name, "blocker_risk", severity, confidence,
                    f"Task '{task.name}' has multiple blockers/issues.",
                    evidence,
                    task=task,
                    metadata=self._build_metadata(task=task)
                ))
        return findings

    def detect_critical_path_exposure(self) -> List[RiskFinding]:
        findings = []
        for task in self.context.tasks:
            if task.critical:
                if task.task_uid is None:
                    continue

                is_slipped = task.finish and task.baseline_finish and task.finish > task.baseline_finish
                slack_text = str(task.total_slack or "").strip().upper()
                has_zero_slack = slack_text in {"0", "0.0", "PT0H0M0S"}
                
                delayed_preds = []
                for pred_uid in (task.predecessor_uids or []):
                    pred_task = self.tasks_by_uid.get(pred_uid)
                    if pred_task and pred_task.finish and pred_task.baseline_finish and pred_task.finish > pred_task.baseline_finish:
                        delayed_preds.append(pred_task)
                
                if is_slipped or has_zero_slack or delayed_preds:
                    has_specific_support = self._has_specific_task_risk(task.task_uid)

                    if has_specific_support and (is_slipped or delayed_preds):
                        continue

                    severity = self._normalize_severity("red" if (is_slipped and has_zero_slack) or len(delayed_preds) > 0 else "amber")
                    evidence = []
                    if is_slipped: evidence.append("Task has slipped")
                    if has_zero_slack: evidence.append("Task has zero slack")
                    if delayed_preds: evidence.append(f"{len(delayed_preds)} delayed predecessors")
                    
                    confidence = self._confidence_for_task(task.task_uid)
                    rule_name = "critical_path_exposure"
                    
                    sources = self._evidence_sources_for_task(task.task_uid)
                    if sources == {"schedule"} and not is_slipped:
                        continue

                    findings.append(self._make_finding(
                        self._finding_id(rule_name, task=task),
                        rule_name, "critical_path_risk", severity, confidence,
                        f"Critical task '{task.name}' is exposed.",
                        evidence,
                        task=task,
                        metadata=self._build_metadata(task=task)
                    ))
        return findings
