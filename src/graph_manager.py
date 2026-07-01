"""
Script Name: graph_manager.py
Description: Manages the knowledge graph of project artifacts and dependencies.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-30
"""

import json
from pathlib import Path
import hashlib
import logging
from typing import List, Dict, Optional, Any
from src.models import (
    ScheduleTask,
    ResourceAssignment,
    RiskSignal,
    Milestone,
    Issue,
    TaskUpdate,
    DeliveryNote,
)

# --- GRAPH MANAGER ---
# This class manages the knowledge graph of project artifacts and their relationships.
# It provides methods to add nodes, edges, and query the graph for specific artifacts or relationships.
# The graph is stored in a JSON file and can be loaded and saved from disk.
#
class GraphManager:
    def __init__(self, graph_path="knowledge_graph/graph.json"):
        self.graph_path = Path(graph_path)
        self.data = {"nodes": {}, "edges": []}
        self.task_id_to_uid_map: Dict[str, str] = {}

    def add_node(self, node_id, node_type, **kwargs):
        new_node = {"id": node_id, "type": node_type, **kwargs}
        if node_id in self.data["nodes"]:
            existing_node = self.data["nodes"][node_id]
            if existing_node == new_node:
                return
            logging.warning(f"Overwriting node {node_id} with different data.")
        self.data["nodes"][node_id] = new_node

    def add_edge(self, from_id, to_id, edge_type, **properties):
        edge = {"from": from_id, "to": to_id, "type": edge_type, **properties}
        if edge not in self.data["edges"]:
            self.data["edges"].append(edge)

    def add_schedule_task(self, task: ScheduleTask):
        t_id = f"task-{task.task_uid}"
        self.task_id_to_uid_map[str(task.task_id)] = str(task.task_uid)
        
        node_data = {
            "task_id": task.task_id,
            "task_uid": task.task_uid,
            "name": task.name,
            "start": task.start.isoformat() if task.start else None,
            "finish": task.finish.isoformat() if task.finish else None,
            "baseline_start": task.baseline_start.isoformat() if task.baseline_start else None,
            "baseline_finish": task.baseline_finish.isoformat() if task.baseline_finish else None,
            "actual_start": task.actual_start.isoformat() if task.actual_start else None,
            "actual_finish": task.actual_finish.isoformat() if task.actual_finish else None,
            "duration": task.duration,
            "remaining_duration": task.remaining_duration,
            "work": task.work,
            "actual_work": task.actual_work,
            "remaining_work": task.remaining_work,
            "percent_complete": task.percent_complete,
            "percent_work_complete": task.percent_work_complete,
            "critical": task.critical,
            "total_slack": task.total_slack,
            "free_slack": task.free_slack,
            "is_milestone": task.is_milestone,
            "status": task.status,
            "notes": task.notes,
            "owner": task.owner,
            "owner_team": task.owner_team,
            "risk_level": task.risk_level,
            "slip_category": task.slip_category,
            "update_health": task.update_health,
            "source_artifact": task.source_artifact,
            "extended_attributes": task.extended_attributes
        }
        self.add_node(t_id, "task", **node_data)

        # Assignments
        for assignment in task.assignments:
            res_id = f"resource-{assignment.resource_uid}"
            self.add_node(res_id, "resource", name=assignment.resource_name, resource_uid=assignment.resource_uid, source_artifact=task.source_artifact)
            self.add_edge(t_id, res_id, "assigned_to", units=assignment.units, work=assignment.work, actual_work=assignment.actual_work)

        # Dependencies
        for pred_uid in task.predecessor_uids:
            self.add_edge(f"task-{pred_uid}", t_id, "precedes")

    def add_milestone(self, m: Milestone):
        m_id = f"milestone-{m.milestone_id}"
        self.add_node(m_id, "milestone", name=m.name, event_date=m.date.isoformat() if m.date else None, status=m.status, source_artifact=m.source_artifact)

        # Dedupe rule: if Milestone.task_uid exists, link the milestone record to task-{task_uid}
        if m.task_uid:
            self.add_edge(m_id, f"task-{m.task_uid}", "references_task")

    def add_issue(self, issue: Issue):
        i_id = f"issue-{issue.issue_id}"
        self.add_node(i_id, "issue", summary=issue.summary, status=issue.status, severity=issue.severity, source_artifact=issue.source_artifact)
        
        # Link issues to tasks by task_uid first, else resolve from task_id.
        task_node_id = None
        if issue.task_uid:
            task_node_id = f"task-{issue.task_uid}"
        elif issue.task_id:
            task_uid = self.task_id_to_uid_map.get(str(issue.task_id))
            if task_uid:
                task_node_id = f"task-{task_uid}"
        
        if task_node_id:
            self.add_edge(i_id, task_node_id, "blocks")
            
        if issue.milestone_id:
            self.add_edge(i_id, f"milestone-{issue.milestone_id}", "blocks")

    def add_task_update(self, update: TaskUpdate):
        raw_id = update.update_id or f"{update.task_uid or update.task_id or 'none'}-{update.event_date.isoformat() if update.event_date else 'nodate'}-{abs(hash(update.narrative))}"
        u_id = f"update-{raw_id}"
        node_data = {
            "event_date": update.event_date.isoformat() if update.event_date else None,
            "status": update.status,
            "percent_complete": update.percent_complete,
            "narrative": update.narrative,
            "task_id": update.task_id,
            "task_uid": update.task_uid,
            "milestone_id": update.milestone_id,
            "source_artifact": update.source_artifact
        }
        self.add_node(u_id, "update", **node_data)
        
        # Link updates to tasks with references or updates.
        task_node_id = None
        if update.task_uid:
            task_node_id = f"task-{update.task_uid}"
        elif update.task_id:
            task_uid = self.task_id_to_uid_map.get(str(update.task_id))
            if task_uid:
                task_node_id = f"task-{task_uid}"
                
        if task_node_id:
            self.add_edge(u_id, task_node_id, "references")
            
        if update.milestone_id:
            self.add_edge(u_id, f"milestone-{update.milestone_id}", "references")

    def add_delivery_note(self, note: DeliveryNote):
        raw_id = note.note_id or f"{note.task_uid or note.task_id or 'none'}-{note.event_date.isoformat() if note.event_date else 'nodate'}-{abs(hash(note.text))}"
        d_id = f"delivery-note-{raw_id}"
        node_data = {
            "text": note.text,
            "event_date": note.event_date.isoformat() if note.event_date else None,
            "task_id": note.task_id,
            "task_uid": note.task_uid,
            "milestone_id": note.milestone_id,
            "source_artifact": note.source_artifact
        }
        self.add_node(d_id, "delivery_note", **node_data)
        
        task_node_id = None
        if note.task_uid:
            task_node_id = f"task-{note.task_uid}"
        elif note.task_id:
            task_uid = self.task_id_to_uid_map.get(str(note.task_id))
            if task_uid:
                task_node_id = f"task-{task_uid}"
        
        if task_node_id:
            self.add_edge(d_id, task_node_id, "references")
            
        if note.milestone_id:
            self.add_edge(d_id, f"milestone-{note.milestone_id}", "references")

    def add_risk_signal(self, signal: RiskSignal):
        # Deterministic id
        unique_key = f"{signal.signal_type}-{signal.task_uid}-{signal.milestone_id}-{signal.evidence}-{signal.source_artifact}"
        task_ref = signal.task_uid if signal.task_uid is not None else 'none'
        milestone_ref = signal.milestone_id if signal.milestone_id is not None else 'none'
        s_id = f"signal-{signal.signal_type}-{task_ref}-{milestone_ref}-{hashlib.md5(unique_key.encode()).hexdigest()[:8]}"
        
        node_data = {
            "signal_type": signal.signal_type,
            "severity": signal.severity,
            "confidence": signal.confidence,
            "evidence": signal.evidence,
            "task_id": signal.task_id,
            "task_uid": signal.task_uid,
            "milestone_id": signal.milestone_id,
            "source_artifact": signal.source_artifact
        }
        self.add_node(s_id, "signal", **node_data)
        
        task_node_id = None
        if signal.task_uid:
            task_node_id = f"task-{signal.task_uid}"
        elif signal.task_id:
            task_uid = self.task_id_to_uid_map.get(str(signal.task_id))
            if task_uid:
                task_node_id = f"task-{task_uid}"
        
        if task_node_id:
            self.add_edge(s_id, task_node_id, "threatens")
            
        if signal.milestone_id:
            self.add_edge(s_id, f"milestone-{signal.milestone_id}", "threatens")

    def build_from_artifacts(self, tasks: List[ScheduleTask], milestones: List[Milestone], 
                             issues: List[Issue], updates: List[TaskUpdate], 
                             delivery_notes: List[DeliveryNote], signals: List[RiskSignal]):
        # Populate task_id_to_uid_map first to support linkages
        print(f" -> Building graph from artifacts.")
        for task in tasks:
            self.task_id_to_uid_map[str(task.task_id)] = str(task.task_uid)

        # Build graph from artifacts.
        # Each adder method creates both the node and necessary edges to avoid missing-target problems.
        for t in tasks: self.add_schedule_task(t)
        for m in milestones: self.add_milestone(m)
        for i in issues: self.add_issue(i)
        for u in updates: self.add_task_update(u)
        for n in delivery_notes: self.add_delivery_note(n)
        for s in signals: self.add_risk_signal(s)

    def get_task_node(self, task_uid: int | str):
        return self.data["nodes"].get(f"task-{task_uid}")

    def get_predecessors(self, task_uid: int | str):
        t_id = f"task-{task_uid}"
        related = [
            e["from"] for e in self.data["edges"]
            if e["to"] == t_id and e["type"] == "precedes"
        ]
        return [self.data["nodes"][rid] for rid in related if rid in self.data["nodes"]]

    def get_successors(self, task_uid: int | str):
        t_id = f"task-{task_uid}"
        related = [
            e["to"] for e in self.data["edges"]
            if e["from"] == t_id and e["type"] == "precedes"
        ]
        return [self.data["nodes"][rid] for rid in related if rid in self.data["nodes"]]

    def get_task_issues(self, task_uid: int | str):
        t_id = f"task-{task_uid}"
        related = [
            e["from"] for e in self.data["edges"]
            if e["to"] == t_id and e["type"] == "blocks"
        ]
        return [self.data["nodes"][rid] for rid in related if rid in self.data["nodes"] and self.data["nodes"][rid]["type"] == "issue"]

    def get_task_signals(self, task_uid: int | str):
        t_id = f"task-{task_uid}"
        related = [
            e["from"] for e in self.data["edges"]
            if e["to"] == t_id and e["type"] == "threatens"
        ]
        return [self.data["nodes"][rid] for rid in related if rid in self.data["nodes"] and self.data["nodes"][rid]["type"] == "signal"]

    def get_milestone_signals(self, milestone_id: int | str):
        m_id = f"milestone-{milestone_id}"
        related = [
            e["from"] for e in self.data["edges"]
            if e["to"] == m_id and e["type"] == "threatens"
        ]
        return [self.data["nodes"][rid] for rid in related if rid in self.data["nodes"] and self.data["nodes"][rid]["type"] == "signal"]

    def get_upstream_chain(self, task_uid: int | str):
        chain = []
        current = task_uid
        while True:
            preds = self.get_predecessors(current)
            if not preds: break
            # Just take the first one for now as a simple chain
            pred = preds[0]
            chain.append(pred)
            current = pred["id"].replace("task-", "")
        return chain

    def save(self):
        directory = self.graph_path.parent
        if directory and not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
        with open(self.graph_path, "w") as f:
            # Flatten nodes for JSON
            output = {
                "nodes": list(self.data["nodes"].values()),
                "edges": self.data["edges"]
            }
            json.dump(output, f, indent=2)

    def load(self):
        with open(self.graph_path, "r") as f:
            raw = json.load(f)
            self.data = {
                "nodes": {n["id"]: n for n in raw["nodes"]},
                "edges": raw["edges"]
            }
