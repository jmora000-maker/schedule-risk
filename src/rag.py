"""
Script Name: rag.py
Description: Retrieval-Augmented Generation engine for schedule-aware artifact retrieval.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-29
"""

from typing import List, Dict, Optional, Any
from collections import defaultdict
from src.models import ArtifactChunk, RiskFinding, RetrievedEvidenceBundle
from src.graph_manager import GraphManager

ARTIFACT_PREFERENCE = {
    "vendor_delay": {"delivery_note", "meeting_note", "issue", "schedule_task"},
    "dependency_delay": {"schedule_task", "task_update", "meeting_note"},
    "milestone_drift": {"milestone", "schedule_task", "meeting_note"},
    "stale_updates": {"task_update", "meeting_note"},
    "readiness_risk": {"meeting_note", "task_update", "issue", "milestone"},
    "blocker_accumulation": {"issue", "meeting_note", "task_update"},
    "critical_path_exposure": {"schedule_task", "milestone", "task_update"},
}

class RAGEngine:
    def __init__(self, chunks: List[ArtifactChunk]):
        self.chunks = chunks
        self.by_task_uid: Dict[str, List[ArtifactChunk]] = defaultdict(list)
        self.by_task_id: Dict[str, List[ArtifactChunk]] = defaultdict(list)
        self.by_milestone_id: Dict[str, List[ArtifactChunk]] = defaultdict(list)
        
        self._index_chunks()

    def _index_chunks(self):
        for chunk in self.chunks:
            if chunk.task_uid is not None:
                self.by_task_uid[str(chunk.task_uid)].append(chunk)
            if chunk.task_id is not None:
                self.by_task_id[str(chunk.task_id)].append(chunk)
            if chunk.milestone_id is not None:
                self.by_milestone_id[str(chunk.milestone_id)].append(chunk)

    def get_chunks_for_task(self, task_uid: Optional[str] = None, task_id: Optional[str] = None, artifact_types: Optional[set[str]] = None) -> List[ArtifactChunk]:
        seen_ids = set()
        results = []
        
        target_uids = [str(task_uid)] if task_uid else []
        target_ids = [str(task_id)] if task_id else []
        
        for uid in target_uids:
            if uid in self.by_task_uid:
                for chunk in self.by_task_uid[uid]:
                    if chunk.chunk_id not in seen_ids:
                        if artifact_types and chunk.artifact_type not in artifact_types:
                            continue
                        results.append(chunk)
                        seen_ids.add(chunk.chunk_id)
        for tid in target_ids:
            if tid in self.by_task_id:
                for chunk in self.by_task_id[tid]:
                    if chunk.chunk_id not in seen_ids:
                        if artifact_types and chunk.artifact_type not in artifact_types:
                            continue
                        results.append(chunk)
                        seen_ids.add(chunk.chunk_id)
        return results

    def get_chunks_for_milestone(self, milestone_id: str, artifact_types: Optional[set[str]] = None) -> List[ArtifactChunk]:
        chunks = self.by_milestone_id.get(str(milestone_id), [])
        if artifact_types:
            chunks = [c for c in chunks if c.artifact_type in artifact_types]
        return chunks

    def get_neighbor_chunks(self, task_uid: str, graph: GraphManager, artifact_types: Optional[set[str]] = None) -> List[ArtifactChunk]:
        neighbors = []
        preds = graph.get_predecessors(task_uid)
        succs = graph.get_successors(task_uid)
        
        for n in preds + succs:
            # Handle node objects (dicts) or node ID strings
            uid = n.get("task_uid") if isinstance(n, dict) else str(n).replace("task-", "")
            
            if uid:
                uid_str = str(uid)
                chunks = self.by_task_uid.get(uid_str, [])
                if artifact_types:
                    chunks = [c for c in chunks if c.artifact_type in artifact_types]
                neighbors.extend(chunks)
        return neighbors

    def _score_chunk(self, chunk: ArtifactChunk, finding: RiskFinding, has_schedule: bool = False) -> float:
        score = 0.0
        if finding.task_uid and str(chunk.task_uid) == str(finding.task_uid):
            score += 2.0
        if finding.milestone_id and chunk.milestone_id == finding.milestone_id:
            score += 2.0
        
        preferred = ARTIFACT_PREFERENCE.get(finding.signal_type, set())
        if chunk.artifact_type in preferred:
            score += 1.0
            
        if chunk.severity and chunk.severity.lower() in {"high", "critical", "red"}:
            score += 1.0
            
        if has_schedule and chunk.artifact_type in {"issue", "task_update", "delivery_note", "meeting_note", "signal"}:
            score += 2.5
            
        return score

    def get_chunks_for_finding(self, finding: RiskFinding, graph: Optional[GraphManager] = None) -> List[ArtifactChunk]:
        chunks = []
        
        # Signal type mapping based on requirements
        
        # 1. Schedule Delay
        if finding.signal_type == "schedule_delay":
            if finding.task_uid:
                # Direct
                chunks.extend(self.get_chunks_for_task(task_uid=str(finding.task_uid)))
                # Predecessors
                if graph:
                    chunks.extend(self.get_neighbor_chunks(str(finding.task_uid), graph))
                # Linked issue/update/signal/delivery-note/meeting-note
                chunks.extend(self.get_chunks_for_task(task_uid=str(finding.task_uid), artifact_types={"issue", "task_update", "signal", "delivery_note", "meeting_note"}))
        
        # 2. Readiness Risk
        elif finding.signal_type == "readiness_risk":
            if finding.task_uid:
                # Direct
                chunks.extend(self.get_chunks_for_task(task_uid=str(finding.task_uid)))
                # Upstream chain (1-level predecessors for now)
                if graph:
                    chunks.extend(self.get_neighbor_chunks(str(finding.task_uid), graph))
                # Readiness/blocker/signoff
                chunks.extend(
                    self.get_chunks_for_task(
                        task_uid=str(finding.task_uid),
                        artifact_types={"task_update", "issue", "meeting_note", "delivery_note", "milestone", "signal"}
                    )
                )
        
        # 3. Milestone Findings
        elif finding.signal_type == "milestone_drift":
            if finding.milestone_id:
                # Milestone chunk
                chunks.extend(self.get_chunks_for_milestone(finding.milestone_id))
                # Milestone task chunk & predecessor
                if finding.task_uid:
                    chunks.extend(self.get_chunks_for_task(task_uid=str(finding.task_uid)))
                    if graph:
                        chunks.extend(self.get_neighbor_chunks(str(finding.task_uid), graph))

        # Default/Fallback
        if not chunks and finding.task_uid:
            chunks.extend(self.get_chunks_for_task(task_uid=str(finding.task_uid)))
            
        # Deduplicate
        seen_keys = set()
        unique_chunks = []
        for c in chunks:
            # dedupe by text plus source artifact
            key = (c.text, c.source_artifact)
            if key not in seen_keys:
                unique_chunks.append(c)
                seen_keys.add(key)
        return unique_chunks

    def build_evidence_bundle(self, finding: RiskFinding, graph: GraphManager) -> RetrievedEvidenceBundle:
        # Get evidence using the source-aware helper
        unique_evidence = self.get_chunks_for_finding(finding, graph)
        
        # Check if there's a schedule chunk
        has_schedule = any(c.artifact_type == "schedule_task" for c in unique_evidence)
        
        # Score and rank
        unique_evidence.sort(key=lambda c: self._score_chunk(c, finding, has_schedule=has_schedule), reverse=True)
        
        grouped: Dict[str, List[ArtifactChunk]] = defaultdict(list)
        milestone_ids = {finding.milestone_id} if finding.milestone_id else set()
        for c in unique_evidence:
            grouped[c.artifact_type].append(c)
            if c.milestone_id:
                milestone_ids.add(c.milestone_id)
            
        # Extract neighbor task IDs for the bundle metadata (re-derive from evidence)
        neighbor_task_ids = set()
        for c in unique_evidence:
            if c.task_uid and str(c.task_uid) != str(finding.task_uid):
                neighbor_task_ids.add(str(c.task_uid))
            
        # Add new fields
        source_types = sorted(set(c.artifact_type for c in unique_evidence))
        non_schedule_types = {t for t in source_types if t != "schedule_task"}
        is_schedule_only = bool(unique_evidence) and not non_schedule_types

        if is_schedule_only:
            evidence_strength = "weak"
        elif len(non_schedule_types) == 1:
            evidence_strength = "moderate"
        else:
            evidence_strength = "strong"
            
        return RetrievedEvidenceBundle(
            finding=finding,
            evidence_bundle=unique_evidence[:10], # Top 10
            grouped_evidence=dict(grouped),
            neighbor_task_ids=list(neighbor_task_ids),
            milestone_ids=list(milestone_ids),
            evidence_strength=evidence_strength,
            source_types=source_types,
            is_schedule_only=is_schedule_only
        )
