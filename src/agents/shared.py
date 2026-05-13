"""Shared dataclasses + types for the spike agents."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CallUserData:
    call_id: str
    patient_queue: list[str] = field(default_factory=list)
    current_patient: Optional[str] = None
    supervisor_in_control: bool = False

    def advance_patient(self) -> Optional[str]:
        """Pop next patient off the queue and set as current. Returns new current, or None if queue empty."""
        if not self.patient_queue:
            self.current_patient = None
            return None
        self.current_patient = self.patient_queue.pop(0)
        return self.current_patient
