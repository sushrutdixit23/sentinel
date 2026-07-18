"""Output shape for a generated narrative — the hypothesis-then-check trail
is kept, not just the final text, so the reasoning is auditable."""

from __future__ import annotations

from pydantic import BaseModel

from sentinel.anomaly.flags import AnomalyFlag


class NarrativeResult(BaseModel):
    flag: AnomalyFlag
    initial_hypothesis: str
    peer_context_given: str
    final_narrative: str
    hypothesis_revised: bool  # did the peer check change the story, per the model's own account?
