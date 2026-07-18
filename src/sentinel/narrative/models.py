"""Output shape for a generated narrative — the hypothesis-then-check trail
is kept, not just the final text, so the reasoning is auditable.

Holds a LIST of flags, not one: a company can trip more than one detector
in the same period (e.g. Apollo's PAT swing + its exceptional item), and
those should be explained together in one narrative pass rather than as
two disconnected writeups that don't reference each other."""

from __future__ import annotations

from pydantic import BaseModel

from sentinel.anomaly.flags import AnomalyFlag


class NarrativeResult(BaseModel):
    company_id: str
    period_label: str
    flags: list[AnomalyFlag]
    initial_hypothesis: str
    peer_context_given: str
    final_narrative: str
    hypothesis_revised: bool  # did the peer check change the story, per the model's own account?
