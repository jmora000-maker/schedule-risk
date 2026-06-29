"""
Script Name: models.py
Description: Data models for the schedule-risk pipeline.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-29
"""

from pydantic import BaseModel, Field, conint, confloat
from typing import Optional, List, Dict, Any
from datetime import datetime, date


class ResourceAssignment(BaseModel):
    resource_uid: Optional[int] = None
    resource_name: Optional[str] = None
    units: Optional[float] = None
    work: Optional[str] = None
    actual_work: Optional[str] = None

    class Config:
        extra = "forbid"


class ScheduleTask(BaseModel):
    task_id: Optional[int] = None
    task_uid: Optional[int] = None
    name: str

    start: Optional[datetime] = None
    finish: Optional[datetime] = None
    baseline_start: Optional[datetime] = None
    baseline_finish: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_finish: Optional[datetime] = None

    duration: Optional[str] = None
    remaining_duration: Optional[str] = None
    work: Optional[str] = None
    actual_work: Optional[str] = None
    remaining_work: Optional[str] = None

    percent_complete: Optional[conint(ge=0, le=100)] = None
    percent_work_complete: Optional[conint(ge=0, le=100)] = None

    critical: Optional[bool] = None
    total_slack: Optional[str] = None
    free_slack: Optional[str] = None
    is_milestone: bool = False

    status: Optional[str] = None
    notes: Optional[str] = None
    owner: Optional[str] = None
    owner_team: Optional[str] = None

    slip_category: Optional[str] = None
    risk_level: Optional[str] = None
    update_health: Optional[str] = None

    predecessor_uids: List[int] = Field(default_factory=list)
    assignments: List[ResourceAssignment] = Field(default_factory=list)
    extended_attributes: Dict[str, Any] = Field(default_factory=dict)
    source_artifact: Optional[str] = None

    class Config:
        extra = "forbid"


class Milestone(BaseModel):
    milestone_id: Optional[str] = None
    name: str
    date: Optional[datetime] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    task_id: Optional[int] = None
    task_uid: Optional[int] = None
    source_artifact: Optional[str] = None

    class Config:
        extra = "forbid"


class Issue(BaseModel):
    issue_id: Optional[str] = None
    summary: str
    status: Optional[str] = None
    severity: Optional[str] = None
    priority: Optional[str] = None
    owner: Optional[str] = None
    created_at: Optional[date] = None
    updated_at: Optional[date] = None
    due_date: Optional[date] = None
    task_id: Optional[int] = None
    task_uid: Optional[int] = None
    milestone_id: Optional[str] = None
    source_artifact: Optional[str] = None

    class Config:
        extra = "forbid"


class TaskUpdate(BaseModel):
    update_id: Optional[str] = None
    event_date: Optional[date] = None
    task_id: Optional[int] = None
    task_uid: Optional[int] = None
    milestone_id: Optional[str] = None
    status: Optional[str] = None
    percent_complete: Optional[conint(ge=0, le=100)] = None
    owner: Optional[str] = None
    narrative: str
    source_artifact: Optional[str] = None

    class Config:
        extra = "forbid"


class DeliveryNote(BaseModel):
    note_id: Optional[str] = None
    event_date: Optional[date] = None
    text: str
    status: Optional[str] = None
    owner: Optional[str] = None
    task_id: Optional[int] = None
    task_uid: Optional[int] = None
    milestone_id: Optional[str] = None
    source_artifact: Optional[str] = None

    class Config:
        extra = "forbid"


class RiskSignal(BaseModel):
    signal_type: str
    severity: Optional[str] = None
    confidence: Optional[confloat(ge=0.0, le=1.0)] = None
    evidence: str

    task_id: Optional[int] = None
    task_uid: Optional[int] = None
    milestone_id: Optional[str] = None

    source_artifact: Optional[str] = None

    class Config:
        extra = "forbid"


class ArtifactChunk(BaseModel):
    chunk_id: str
    artifact_type: str
    source_artifact: str
    text: str

    task_id: Optional[int] = None
    task_uid: Optional[int] = None
    milestone_id: Optional[str] = None
    issue_id: Optional[str] = None

    severity: Optional[str] = None
    confidence: Optional[confloat(ge=0.0, le=1.0)] = None
    event_date: Optional[date] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    progress: Optional[conint(ge=0, le=100)] = None

    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "forbid"


class RiskFinding(BaseModel):
    finding_id: str
    rule_name: str
    signal_type: str
    severity: str
    confidence: float
    summary: str
    evidence: List[str] = Field(default_factory=list)
    task_id: Optional[int] = None
    task_uid: Optional[int] = None
    milestone_id: Optional[str] = None
    source_artifact: Optional[str] = None
    related_signals: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "forbid"


class RiskExplanation(BaseModel):
    finding_id: str
    summary: str
    impact: str
    recommended_action: str
    evidence_used: List[str]

    class Config:
        extra = "forbid"


class RetrievedContext(BaseModel):
    chunks: List[ArtifactChunk] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "forbid"


class RetrievedEvidenceBundle(BaseModel):
    finding: RiskFinding
    evidence_bundle: List[ArtifactChunk] = Field(default_factory=list)
    grouped_evidence: Dict[str, List[ArtifactChunk]] = Field(default_factory=dict)
    neighbor_task_ids: List[str] = Field(default_factory=list)
    milestone_ids: List[str] = Field(default_factory=list)
    evidence_strength: str = "strong"
    source_types: List[str] = Field(default_factory=list)
    is_schedule_only: bool = False

    class Config:
        extra = "forbid"
