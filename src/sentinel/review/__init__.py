"""
Review/approval layer — makes narratives DRAFTS, not final output, until a
human explicitly approves (with or without edits) or rejects them. This is
the supervised, approval-gated pattern from [[zyntask-engage]]'s magic
review link, applied to Sentinel: nothing an AI drafts here counts as "the
analysis" on its own.
"""

from sentinel.review.models import ReviewRecord, ReviewStatus
from sentinel.review.store import (
    approve_review,
    create_pending_review,
    list_reviews,
    load_review,
    reject_review,
    save_review,
)

__all__ = [
    "ReviewRecord",
    "ReviewStatus",
    "create_pending_review",
    "save_review",
    "load_review",
    "list_reviews",
    "approve_review",
    "reject_review",
]
