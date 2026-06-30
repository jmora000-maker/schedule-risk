"""
Script Name: inputs.py
Description: Ingests project artifacts like schedules and meeting notes.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-29
"""

from typing import List, Dict, Set, Any
import re
import uuid
import csv
from pathlib import Path
from datetime import datetime, date
from docx import Document
from src.config import (
    meeting_notes_path,
    schedule_path,
    milestones_path,
    issue_log_path,
    task_updates_path,
    delivery_notes_path,
    graph_path,
)
from src.taxonomy import CorporateTaxonomyNormalizer
from src.models import (
    ScheduleTask,
    ResourceAssignment,
    RiskSignal,
    Milestone,
    Issue,
    TaskUpdate,
    DeliveryNote,
    ArtifactChunk,
)
from src.graph_manager import GraphManager
from src.utils import parse_int
import xml.etree.ElementTree as ET


# --- PIPELINE LAYER: ARTIFACT-SPECIFIC INGESTION & STRUCTURAL FACTS ENGINE ---
class ProjectArtifactLoader:
    """Dynamic Document Content Ingestion executing explicit parsers with dense metadata population."""

    def __init__(self, normalizer: CorporateTaxonomyNormalizer):
        self.normalizer = normalizer
        self.tasks: List[ScheduleTask] = []
        self.signals: List[RiskSignal] = []
        self.milestones: List[Milestone] = []
        self.issues: List[Issue] = []
        self.task_updates: List[TaskUpdate] = []
        self.delivery_notes: List[DeliveryNote] = []
        self.raw_chunks: List[ArtifactChunk] = []
        self.task_id_to_uid_map: Dict[int, int] = {}
        self.task_name_to_task: Dict[str, ScheduleTask] = {}
        self.task_aliases = {
            "requirements planning": "Requirements and Design",
            "requirements and planning": "Requirements and Design",
            "build phase": "Build",
            "vendor delivery": "Vendor Delivery",
            "integration and test": "Integration and Test",
            "integration test": "Integration and Test",
            "readiness review": "Deployment Readiness",
            "production signoff": "Production Signoff Milestone",
        }
        self.ingestion_failures: Dict[str, int] = {}

    def _make_chunk(
        self,
        *,
        artifact_type: str,
        source_artifact: str,
        text: str,
        task_id: int | None = None,
        task_uid: int | None = None,
        milestone_id: str | None = None,
        issue_id: str | None = None,
        owner: str | None = None,
        status: str | None = None,
        progress: int | None = None,
        severity: str | None = None,
        confidence: float | None = None,
        event_date: date | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> ArtifactChunk:
        return ArtifactChunk(
            chunk_id=uuid.uuid4().hex,
            artifact_type=artifact_type,
            source_artifact=source_artifact,
            text=text,
            task_id=task_id,
            task_uid=task_uid,
            milestone_id=milestone_id,
            issue_id=issue_id,
            owner=owner,
            status=status,
            progress=progress,
            severity=severity,
            confidence=confidence,
            event_date=event_date,
            metadata=metadata or {},
        )

    def _parse_bool(self, val):
        return str(val).strip().lower() in {"1", "true", "yes"}

    def _parse_datetime(self, val):
        if not val: return None
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _parse_date(self, val):
        if not val: return None
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
        except ValueError:
            return None

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

    def load_project_artifacts(self, project_dir: Path):
        print(" -> Ingesting Project Artifacts.")
        self.tasks.extend(self.load_schedule_file(project_dir / "compact_schedule.xml"))
        self.load_meeting_notes(project_dir / "meeting_notes_v3.docx")
        self.load_milestones(project_dir / "milestones.csv")
        self.load_issue_log(project_dir / "issue_log.csv")
        self.load_task_updates(project_dir / "task_updates.csv")
        self.load_delivery_notes(project_dir / "delivery_notes.txt")


    def _read_meeting_notes(self, path) -> List[str]:
        if not path.exists():
            return []

        try:
            suffix = path.suffix.lower()

            if suffix in [".txt", ".md"]:
                return path.read_text(encoding="utf-8").splitlines()

            if suffix == ".docx":
                doc = Document(path)
                lines = []
                for para in doc.paragraphs:
                    text = para.text.strip()
                    if text:
                        lines.append(text)
                return lines

            print(f"Unsupported meeting notes format: {path}")
            self.ingestion_failures[path.name] = self.ingestion_failures.get(path.name, 0) + 1
            return []

        except Exception as e:
            print(f"Error reading meeting notes {path}: {e}")
            self.ingestion_failures[path.name] = self.ingestion_failures.get(path.name, 0) + 1
            return []

    def load_meeting_notes(self, path):
        print(f" -> Loading meeting notes: {path.name}")
        if not path.exists():
            self.ingestion_failures[path.name] = self.ingestion_failures.get(path.name, 0) + 1
            return
        lines = self._read_meeting_notes(path)
        if not lines:
            return
        
        self.signals.extend(self.load_meeting_note_signals_from_lines(lines, path))

    def load_milestones(self, path: Path):
        print(f" -> Loading milestones: {path.name}")
        if not path.exists():
            self.ingestion_failures[path.name] = self.ingestion_failures.get(path.name, 0) + 1
            return
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                milestone = Milestone(
                    milestone_id=row.get("milestone_id") or None,
                    name=row.get("name", ""),
                    date=self._parse_datetime(row.get("date")),
                    status=row.get("status") or None,
                    owner=row.get("owner") or None,
                    task_id=parse_int(row.get("task_id")),
                    task_uid=parse_int(row.get("task_uid")),
                    source_artifact=path.name,
                )
                self.milestones.append(milestone)
                self.raw_chunks.append(self._make_chunk(
                    artifact_type="milestone",
                    source_artifact=path.name,
                    text=f"Milestone: {milestone.name} (Target: {milestone.date})",
                    milestone_id=milestone.milestone_id
                ))

    def load_issue_log(self, path: Path):
        print(f" -> Loading issue log: {path.name}")
        if not path.exists():
            self.ingestion_failures[path.name] = self.ingestion_failures.get(path.name, 0) + 1
            return
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                issue = Issue(
                    issue_id=row.get("issue_id") or None,
                    summary=row.get("summary", ""),
                    status=row.get("status") or None,
                    severity=row.get("severity") or None,
                    priority=row.get("priority") or None,
                    owner=row.get("owner") or None,
                    created_at=self._parse_date(row.get("created_at")),
                    updated_at=self._parse_date(row.get("updated_at")),
                    due_date=self._parse_date(row.get("due_date")),
                    task_id=parse_int(row.get("task_id")),
                    task_uid=parse_int(row.get("task_uid")),
                    milestone_id=row.get("milestone_id") or None,
                    source_artifact=path.name,
                )
                self.issues.append(issue)
                self.raw_chunks.append(self._make_chunk(
                    artifact_type="issue",
                    source_artifact=path.name,
                    text=f"Issue: {issue.summary}",
                    issue_id=issue.issue_id,
                    task_uid=issue.task_uid,
                    severity=issue.severity
                ))

    def load_task_updates(self, path: Path):
        print(f" -> Loading task updates: {path.name}")
        if not path.exists():
            self.ingestion_failures[path.name] = self.ingestion_failures.get(path.name, 0) + 1
            return
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                update = TaskUpdate(
                    update_id=row.get("update_id") or None,
                    event_date=self._parse_date(row.get("event_date")),
                    task_id=parse_int(row.get("task_id")),
                    task_uid=parse_int(row.get("task_uid")),
                    milestone_id=row.get("milestone_id") or None,
                    status=row.get("status") or None,
                    percent_complete=parse_int(row.get("percent_complete")),
                    owner=row.get("owner") or None,
                    narrative=row.get("narrative", ""),
                    source_artifact=path.name,
                )
                self.task_updates.append(update)
                self.raw_chunks.append(self._make_chunk(
                    artifact_type="task_update",
                    source_artifact=path.name,
                    text=f"Update: {update.narrative}",
                    task_uid=update.task_uid,
                    status=update.status
                ))

    def load_delivery_notes(self, path: Path):
        print(f" -> Loading delivery notes: {path.name}")
        if not path.exists():
            self.ingestion_failures[path.name] = self.ingestion_failures.get(path.name, 0) + 1
            return
        with open(path, "r", encoding="utf-8") as f:
            # Assuming simple text format
            text = f.read()
            note = DeliveryNote(
                text=text,
                source_artifact=path.name,
                note_id=None,
                event_date=None,
                status=None,
                owner=None,
                task_id=None,
                task_uid=None,
                milestone_id=None,
            )
            self.delivery_notes.append(note)
            self.raw_chunks.append(self._make_chunk(
                artifact_type="delivery_note",
                source_artifact=path.name,
                text=f"Delivery Note: {text[:200]}...",
                task_id=None,
                task_uid=None,
                milestone_id=None,
            ))



    def load_meeting_note_signals_from_lines(self, lines, path) -> List[RiskSignal]:
        signals = []
        seen_signals = {} # (task_id, milestone_id, signal_type): count

        for idx, line in enumerate(lines):
            lowered = line.lower()
            # Enhanced linking: distinguish Task ID from UID
            task_id = None
            task_uid = None
            
            task_match = re.search(r"(task|uid)\s*(\d+)", lowered)
            milestone_match = re.search(r"milestone\s*(\d+)", lowered)
            
            if task_match:
                match_type = task_match.group(1)
                value = parse_int(task_match.group(2))
                if match_type == "task":
                    task_id = value
                    task_uid = self.task_id_to_uid_map.get(task_id)
                elif match_type == "uid":
                    task_uid = value
            
            milestone_id = milestone_match.group(1) if milestone_match else None

            # Name-based resolution
            if task_id is None and task_uid is None:
                line_norm = self._normalize_text(line)
                matched_task = None
                
                # Check aliases first
                for alias, canonical_name in self.task_aliases.items():
                    if alias in line_norm:
                        target = self.task_name_to_task.get(self._normalize_text(canonical_name))
                        if target:
                            matched_task = target
                            break
                
                # If not found by alias, check task names
                if not matched_task:
                    for norm_name, task in self.task_name_to_task.items():
                        if norm_name and norm_name in line_norm:
                            matched_task = task
                            break
                
                if matched_task:
                    task_id = matched_task.task_id
                    task_uid = matched_task.task_uid

            # Get signal structure from normalizer
            sig = self.normalizer.classify_concern(
                line,
                task_id=parse_int(task_id),
                task_uid=parse_int(task_uid),
                milestone_id=milestone_id,
                source_artifact=path.name
            )
            
            # If a valid signal type was identified (not the default friction)
            if sig.signal_type != "general_operational_friction":
                # Escalation logic
                key = (task_id, task_uid, milestone_id, sig.signal_type)
                if seen_signals.get(key, 0) > 0:
                    if sig.severity == "medium": sig.severity = "high"
                    elif sig.severity == "high": sig.severity = "critical"
                seen_signals[key] = seen_signals.get(key, 0) + 1
                
                signals.append(sig)
                self.raw_chunks.append(self._make_chunk(
                    artifact_type="meeting_note_signal",
                    source_artifact=path.name,
                    text=f"Signal {sig.signal_type}: {line.strip()}",
                    task_id=sig.task_id,
                    task_uid=sig.task_uid,
                    milestone_id=milestone_id,
                    owner=None,
                    status="open",
                    severity=sig.severity,
                    confidence=sig.confidence,
                    event_date=None,
                    metadata={"signal_type": sig.signal_type},
                ))
        return signals

    def load_schedule_file(self, path) -> List[ScheduleTask]:
        print(f" -> Loading schedule file: {path.name}")
        if not path.exists():
            self.ingestion_failures[path.name] = self.ingestion_failures.get(path.name, 0) + 1
            return []
        ns = {"ms": "http://schemas.microsoft.com/project"}
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as e:
            print(f"Error parsing {path}: {e}")
            self.ingestion_failures[path.name] = self.ingestion_failures.get(path.name, 0) + 1
            return []
        except Exception as e:
            print(f"Error loading {path}: {e}")
            self.ingestion_failures[path.name] = self.ingestion_failures.get(path.name, 0) + 1
            return []
        tasks = []

        # Resources lookup
        resources = {}
        for res in root.findall("ms:Resources/ms:Resource", ns):
            uid = res.findtext("ms:UID", default="", namespaces=ns)
            name = res.findtext("ms:Name", default="", namespaces=ns)
            if uid: resources[uid] = name

        # Assignments lookup
        assignments_map = {}
        for assgn in root.findall("ms:Assignments/ms:Assignment", ns):
            task_uid = assgn.findtext("ms:TaskUID", default="", namespaces=ns)
            res_uid = assgn.findtext("ms:ResourceUID", default="", namespaces=ns)
            if task_uid and res_uid:
                res_name = resources.get(res_uid, "Unknown")
                assignments_map.setdefault(task_uid, []).append(
                    ResourceAssignment(
                        resource_uid=parse_int(res_uid),
                        resource_name=res_name
                    )
                )

        # 2. Normalized extended attribute mapping
        FIELD_MAP = {
            "188743731": "slip_category",
            "188743732": "risk_level",
            "188743733": "owner_team",
            "188743734": "update_health",
        }

        for task in root.findall("ms:Tasks/ms:Task", ns):
            task_uid = task.findtext("ms:UID", default="", namespaces=ns)
            
            # Predecessors parsing
            preds = [
                pl.findtext("ms:PredecessorUID", default="", namespaces=ns)
                for pl in task.findall("ms:PredecessorLink", ns)
            ]
            
            # Milestone and Extended Attributes
            is_milestone = task.findtext("ms:Milestone", default="0", namespaces=ns) == "1"
            ext_attrs = {}
            for ext in task.findall("ms:ExtendedAttribute", ns):
                field_id = ext.findtext("ms:FieldID", default="", namespaces=ns)
                value = ext.findtext("ms:Value", default="", namespaces=ns)
                if field_id:
                    attr_name = FIELD_MAP.get(field_id, field_id)
                    ext_attrs[attr_name] = value

            name = task.findtext("ms:Name", default="", namespaces=ns)
            start_raw = task.findtext("ms:Start", default="", namespaces=ns)
            finish_raw = task.findtext("ms:Finish", default="", namespaces=ns)
            percent_complete = parse_int(task.findtext("ms:PercentComplete", default="", namespaces=ns))
            task_id = parse_int(task.findtext("ms:ID", default="", namespaces=ns))
            task_uid = parse_int(task.findtext("ms:UID", default="", namespaces=ns))
            if task_uid is None:
                continue

            tasks.append(ScheduleTask(
                task_uid=task_uid,
                task_id=task_id,
                name=name,
                start=self._parse_datetime(start_raw),
                finish=self._parse_datetime(finish_raw),
                baseline_start=self._parse_datetime(task.findtext("ms:Baseline/ms:Start", default="", namespaces=ns)),
                baseline_finish=self._parse_datetime(task.findtext("ms:Baseline/ms:Finish", default="", namespaces=ns)),
                actual_start=self._parse_datetime(task.findtext("ms:ActualStart", default="", namespaces=ns)),
                actual_finish=self._parse_datetime(task.findtext("ms:ActualFinish", default="", namespaces=ns)),
                percent_complete=percent_complete,
                remaining_duration=task.findtext("ms:RemainingDuration", default="", namespaces=ns),
                critical=self._parse_bool(task.findtext("ms:Critical", default="", namespaces=ns)),
                total_slack=task.findtext("ms:TotalSlack", default="", namespaces=ns),
                notes=task.findtext("ms:Notes", default="", namespaces=ns),
                source_artifact=path.name,
                predecessor_uids=[int(p) for p in preds if p and p.isdigit()],
                assignments=assignments_map.get(str(task_uid), []),
                is_milestone=is_milestone,
                extended_attributes=ext_attrs,
                slip_category=ext_attrs.get("slip_category"),
                risk_level=ext_attrs.get("risk_level"),
                owner_team=ext_attrs.get("owner_team"),
                update_health=ext_attrs.get("update_health"),
            ))
            
            if task_id is not None and task_uid is not None:
                self.task_id_to_uid_map[task_id] = task_uid
            
            self.raw_chunks.append(self._make_chunk(
                artifact_type="schedule_task",
                source_artifact=path.name,
                text=f"Task: {name}, Start: {start_raw}, Finish: {finish_raw}",
                task_id=task_id,
                task_uid=task_uid,
                progress=percent_complete,
                event_date=self._parse_date(start_raw),
            ))
        
        for task in tasks:
            norm = self._normalize_text(task.name)
            if norm:
                self.task_name_to_task[norm] = task

        return tasks


    def ingest_all(self):
        self.tasks.extend(self.load_schedule_file(schedule_path))
        self.load_meeting_notes(meeting_notes_path)
        self.load_milestones(milestones_path)
        self.load_issue_log(issue_log_path)
        self.load_task_updates(task_updates_path)
        self.load_delivery_notes(delivery_notes_path)
        self.print_ingestion_summary()
        self.build_graph()

    def ingest_data(self):
        self.ingest_all()

    def build_graph(self):
        print(" -> Building Knowledge Graph.")
        graph = GraphManager(graph_path=graph_path)
        graph.build_from_artifacts(
            self.tasks,
            self.milestones,
            self.issues,
            self.task_updates,
            self.delivery_notes,
            self.signals,
        )
        graph.save()

    def print_ingestion_summary(self):
        print(" -> Ingestion summary")
        print(f"    tasks: {len(self.tasks)}")
        print(f"    milestones: {len(self.milestones)}")
        print(f"    issues: {len(self.issues)}")
        print(f"    task_updates: {len(self.task_updates)}")
        print(f"    delivery_notes: {len(self.delivery_notes)}")
        print(f"    signals: {len(self.signals)}")
        print(f"    raw_chunks: {len(self.raw_chunks)}")
        print(f"    failures: {self.ingestion_failures}")