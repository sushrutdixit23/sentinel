"""
The review/approval data model — this is what makes narratives drafts
instead of final output. Nothing downstream should treat a narrative as
"the analysis" until its status is APPROVED or EDITED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from sentinel.anomaly.flags import AnomalyFlag


class ReviewStatus(str, Enum):
    PENDING = "pending"      # AI draft generated, awaiting human review
    APPROVED = "approved"    # human approved the AI draft as-is
    EDITED = "edited"        # human approved with edits — final_narrative differs from ai_narrative
    REJECTED = "rejected"    # human rejected — not to be used as output


class ReviewRecord(BaseModel):
    company_id: str
    company_name: str
    period_label: str
    flags: list[AnomalyFlag]

    # The AI's draft — never mutated after generation, so there's always a
    # record of what was actually produced versus what a human approved.
    initial_hypothesis: str
    peer_context_given: str
    ai_narrative: str

    status: ReviewStatus = ReviewStatus.PENDING
    # None until reviewed. Equals ai_narrative if approved unedited;
    # differs from it if EDITED; irrelevant (but left as last draft) if REJECTED.
    final_narrative: Optional[str] = None
    reviewer_notes: Optional[str] = None

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_at: Optional[datetime] = None

    @property
    def is_final(self) -> bool:
        """True only when a human has signed off — the entire point of
        this module. An AI draft alone is never final, regardless of how
        confident the narrative reads."""
        return self.status in (ReviewStatus.APPROVED, ReviewStatus.EDITED)
