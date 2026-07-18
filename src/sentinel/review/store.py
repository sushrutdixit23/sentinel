"""
Persists ReviewRecords as one JSON file per (company_id, period_label) —
same convention as data/extracted/, so review history is visible in git
diffs like everything else in this repo, not hidden inside a database file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from sentinel.narrative.models import NarrativeResult
from sentinel.review.models import ReviewRecord, ReviewStatus

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REVIEWS_DIR = REPO_ROOT / "data" / "reviews"


def _path_for(company_id: str, period_label: str, reviews_dir: Path | None = None) -> Path:
    reviews_dir = reviews_dir or DEFAULT_REVIEWS_DIR
    return reviews_dir / f"{company_id}__{period_label}.json"


def create_pending_review(result: NarrativeResult) -> ReviewRecord:
    """Build a fresh PENDING review record from a freshly generated narrative.
    Does not save it — call save_review() explicitly."""
    return ReviewRecord(
        company_id=result.company_id,
        company_name=result.flags[0].company_name,
        period_label=result.period_label,
        flags=result.flags,
        initial_hypothesis=result.initial_hypothesis,
        peer_context_given=result.peer_context_given,
        ai_narrative=result.final_narrative,
        status=ReviewStatus.PENDING,
    )


def save_review(record: ReviewRecord, reviews_dir: Path | None = None) -> None:
    reviews_dir = reviews_dir or DEFAULT_REVIEWS_DIR
    reviews_dir.mkdir(parents=True, exist_ok=True)
    path = _path_for(record.company_id, record.period_label, reviews_dir)
    path.write_text(record.model_dump_json(indent=2))


def load_review(
    company_id: str, period_label: str, reviews_dir: Path | None = None
) -> Optional[ReviewRecord]:
    path = _path_for(company_id, period_label, reviews_dir)
    if not path.exists():
        return None
    return ReviewRecord.model_validate_json(path.read_text())


def list_reviews(reviews_dir: Path | None = None) -> list[ReviewRecord]:
    reviews_dir = reviews_dir or DEFAULT_REVIEWS_DIR
    if not reviews_dir.exists():
        return []
    records = []
    for path in sorted(reviews_dir.glob("*.json")):
        records.append(ReviewRecord.model_validate_json(path.read_text()))
    return records


def approve_review(
    record: ReviewRecord, edited_text: Optional[str] = None, notes: Optional[str] = None
) -> ReviewRecord:
    """Returns a new record with status APPROVED (unedited) or EDITED
    (edited_text differs from the AI draft) and reviewed_at set. Caller
    still needs to save_review() the result — this function doesn't
    persist anything itself, keeping it a pure, easily testable transform."""
    from datetime import datetime, timezone

    final_text = edited_text if edited_text is not None else record.ai_narrative
    status = ReviewStatus.EDITED if final_text.strip() != record.ai_narrative.strip() else ReviewStatus.APPROVED
    return record.model_copy(
        update={
            "status": status,
            "final_narrative": final_text,
            "reviewer_notes": notes,
            "reviewed_at": datetime.now(timezone.utc),
        }
    )


def reject_review(record: ReviewRecord, notes: Optional[str] = None) -> ReviewRecord:
    from datetime import datetime, timezone

    return record.model_copy(
        update={
            "status": ReviewStatus.REJECTED,
            "final_narrative": None,
            "reviewer_notes": notes,
            "reviewed_at": datetime.now(timezone.utc),
        }
    )
