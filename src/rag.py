"""
Script Name: rag.py
Description: Retrieval-Augmented Generation engine for schedule-aware artifact retrieval.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-28
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
        chunks = self.by_milestone_id.get(milestone_id, [])
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

    def _score_chunk(self, chunk: ArtifactChunk, finding: RiskFinding) -> float:
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
        return score

    def build_evidence_bundle(self, finding: RiskFinding, graph: GraphManager) -> RetrievedEvidenceBundle:
        evidence = []
        
        # 1. Directly linked
        if finding.task_uid:
            evidence.extend(self.get_chunks_for_task(task_uid=str(finding.task_uid)))
        if finding.milestone_id:
            evidence.extend(self.get_chunks_for_milestone(finding.milestone_id))
            
        # 2. Neighbors
        neighbor_task_ids = []
        if finding.task_uid:
            # Simple depth 1 neighbors
            preds = graph.get_predecessors(finding.task_uid)
            succs = graph.get_successors(finding.task_uid)
            for n in preds + succs:
                uid = n.get("task_uid") if isinstance(n, dict) else str(n).replace("task-", "")
                if uid:
                    neighbor_task_ids.append(str(uid))
                    evidence.extend(self.get_chunks_for_task(task_uid=str(uid)))
            
        # Deduplicate
        seen_ids = set()
        unique_evidence = []
        for c in evidence:
            if c.chunk_id not in seen_ids:
                unique_evidence.append(c)
                seen_ids.add(c.chunk_id)
        
        # Score and rank
        unique_evidence.sort(key=lambda c: self._score_chunk(c, finding), reverse=True)
        
        grouped: Dict[str, List[ArtifactChunk]] = defaultdict(list)
        milestone_ids = {finding.milestone_id} if finding.milestone_id else set()
        for c in unique_evidence:
            grouped[c.artifact_type].append(c)
            if c.milestone_id:
                milestone_ids.add(c.milestone_id)
            
        return RetrievedEvidenceBundle(
            finding=finding,
            evidence_bundle=unique_evidence[:10], # Top 10
            grouped_evidence=dict(grouped),
            neighbor_task_ids=list(set(neighbor_task_ids)),
            milestone_ids=list(milestone_ids)
        )
