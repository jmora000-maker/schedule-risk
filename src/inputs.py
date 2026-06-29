"""
Script Name: inputs.py
Description: Ingests project artifacts like schedules and meeting notes.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-29
"""

from typing import List, Dict, Set
import re
import uuid
from pathlib import Path
from datetime import datetime, date
from docx import Document
from src.config import (
    meeting_notes_path,
    schedule_path,
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
        self.task_id_to_uid_map: Dict[str, str] = {}
        self.ingestion_failures: Dict[str, int] = {}

    def _parse_bool(self, val):
        return val == "1"

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

    def load_project_artifacts(self, project_dir: Path):
        print(" -> Ingesting Project Artifacts.")
        self.tasks.extend(self.load_schedule_file(project_dir / "compact_schedule.xml"))
        self.load_meeting_notes(project_dir / "meeting_notes_v3.docx")


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
        lines = self._read_meeting_notes(path)
        if not lines: return
        
        self.signals.extend(self.load_meeting_note_signals_from_lines(lines, path))



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
                value = task_match.group(2)
                if match_type == "task":
                    task_id = value
                    task_uid = self.task_id_to_uid_map.get(task_id)
                elif match_type == "uid":
                    task_uid = value
            
            milestone_id = milestone_match.group(1) if milestone_match else None

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
                key = (task_id, milestone_id, sig.signal_type)
                if seen_signals.get(key, 0) > 0:
                    if sig.severity == "medium": sig.severity = "high"
                    elif sig.severity == "high": sig.severity = "critical"
                seen_signals[key] = seen_signals.get(key, 0) + 1
                
                signals.append(sig)
                self.raw_chunks.append(ArtifactChunk(
                    chunk_id=uuid.uuid4().hex,
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
                ))
        return signals

    def load_schedule_file(self, path) -> List[ScheduleTask]:
        print(f" -> Loading schedule file: {path.name}")
        if not path.exists(): return []
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

            tasks.append(ScheduleTask(
                task_uid=parse_int(task_uid),
                task_id=parse_int(task.findtext("ms:ID", default="", namespaces=ns)),
                name=task.findtext("ms:Name", default="", namespaces=ns),
                start=self._parse_datetime(task.findtext("ms:Start", default="", namespaces=ns)),
                finish=self._parse_datetime(task.findtext("ms:Finish", default="", namespaces=ns)),
                baseline_start=self._parse_datetime(task.findtext("ms:Baseline/ms:Start", default="", namespaces=ns)),
                baseline_finish=self._parse_datetime(task.findtext("ms:Baseline/ms:Finish", default="", namespaces=ns)),
                actual_start=self._parse_datetime(task.findtext("ms:ActualStart", default="", namespaces=ns)),
                actual_finish=self._parse_datetime(task.findtext("ms:ActualFinish", default="", namespaces=ns)),
                percent_complete=parse_int(task.findtext("ms:PercentComplete", default="", namespaces=ns)),
                remaining_duration=task.findtext("ms:RemainingDuration", default="", namespaces=ns),
                critical=self._parse_bool(task.findtext("ms:Critical", default="", namespaces=ns)),
                total_slack=task.findtext("ms:TotalSlack", default="", namespaces=ns),
                notes=task.findtext("ms:Notes", default="", namespaces=ns),
                source_artifact=path.name,
                predecessor_uids=[int(p) for p in preds if p and p.isdigit()],
                assignments=assignments_map.get(task_uid, []),
                is_milestone=is_milestone,
                extended_attributes=ext_attrs,
                slip_category=ext_attrs.get("slip_category"),
                risk_level=ext_attrs.get("risk_level"),
                owner_team=ext_attrs.get("owner_team"),
                update_health=ext_attrs.get("update_health"),
            ))
            
            self.task_id_to_uid_map[task.findtext("ms:ID", default="", namespaces=ns)] = task_uid
            
            self.raw_chunks.append(ArtifactChunk(
                chunk_id=uuid.uuid4().hex,
                artifact_type="schedule_task",
                source_artifact=path.name,
                text=f"Task: {task.findtext('ms:Name', default='', namespaces=ns)}, Start: {task.findtext('ms:Start', default='', namespaces=ns)}, Finish: {task.findtext('ms:Finish', default='', namespaces=ns)}",
                task_id=parse_int(task.findtext("ms:ID", default="", namespaces=ns)),
                task_uid=parse_int(task_uid),
                owner=None,
                status=None,
                progress=parse_int(task.findtext("ms:PercentComplete", default="0")),
                severity=None,
                event_date=self._parse_date(task.findtext("ms:Start", default="")),
            ))
        return tasks


    def ingest_all(self):
        self.tasks.extend(self.load_schedule_file(schedule_path))
        self.load_meeting_notes(meeting_notes_path)
        
        self.build_graph()

    def ingest_data(self):
        self.ingest_all()

    def build_graph(self):
        print(" -> Building Knowledge Graph.")
        graph = GraphManager(graph_path="knowledge_graph/graph.json")
        graph.build_from_artifacts(
            self.tasks, 
            self.milestones, 
            self.issues, 
            self.task_updates, 
            self.delivery_notes, 
            self.signals
        )
        graph.save()