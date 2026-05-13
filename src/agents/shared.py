"""Shared dataclasses + types for the spike agents."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CallUserData:
    """Per-call session userdata. Carried via AgentSession[CallUserData]."""

    call_id: str
    # Stack of patients yet to process. Day 2 will use this.
    patient_queue: list[str] = field(default_factory=list)
    current_patient: Optional[str] = None
    # Set True by takeover toggle (Day 3).
    supervisor_in_control: bool = False
