import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel.anomaly import run_all_checks  # noqa: E402
from sentinel.engine import build_peer_table  # noqa: E402
from sentinel.ingestion import load_all, load_company_config, load_sector_config  # noqa: E402
from sentinel.narrative import group_flags_by_company  # noqa: E402
from sentinel.narrative.models import NarrativeResult  # noqa: E402
from sentinel.review import (  # noqa: E402
    ReviewStatus,
    approve_review,
    create_pending_review,
    list_reviews,
    load_review,
    reject_review,
    save_review,
)


def _sample_narrative_result() -> NarrativeResult:
    company_config = load_company_config()
    sector_config = load_sector_config(company_config["sector"])
    statements = load_all()
    fy26 = [s for s in statements if s.period_label == "FY26"]
    peer_df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    flags = run_all_checks(fy26, peer_df, sector_config)
    groups = group_flags_by_company(flags)
    apollo_group = next(g for g in groups if g[0].company_id == "apollo_tyres")

    return NarrativeResult(
        company_id="apollo_tyres",
        period_label="FY26",
        flags=apollo_group,
        initial_hypothesis="test hypothesis",
        peer_context_given="test peer context",
        final_narrative="test AI-drafted narrative",
        hypothesis_revised=False,
    )


def test_new_review_starts_pending_and_not_final():
    record = create_pending_review(_sample_narrative_result())
    assert record.status == ReviewStatus.PENDING
    assert record.is_final is False
    assert record.final_narrative is None


def test_approve_unedited_sets_status_approved():
    record = create_pending_review(_sample_narrative_result())
    approved = approve_review(record, edited_text=None)
    assert approved.status == ReviewStatus.APPROVED
    assert approved.is_final is True
    assert approved.final_narrative == record.ai_narrative
    assert approved.reviewed_at is not None


def test_approve_with_edits_sets_status_edited():
    record = create_pending_review(_sample_narrative_result())
    edited = approve_review(record, edited_text="a human rewrote this completely")
    assert edited.status == ReviewStatus.EDITED
    assert edited.is_final is True
    assert edited.final_narrative == "a human rewrote this completely"
    assert edited.ai_narrative == "test AI-drafted narrative"  # original draft preserved


def test_approve_with_edited_text_identical_to_draft_counts_as_approved_not_edited():
    """If the 'edit' is just the same text with different whitespace, that's
    not a real edit — don't misrepresent it as EDITED."""
    record = create_pending_review(_sample_narrative_result())
    approved = approve_review(record, edited_text="  test AI-drafted narrative  ")
    assert approved.status == ReviewStatus.APPROVED


def test_reject_clears_final_narrative():
    record = create_pending_review(_sample_narrative_result())
    rejected = reject_review(record, notes="not accurate, missing context")
    assert rejected.status == ReviewStatus.REJECTED
    assert rejected.is_final is False
    assert rejected.final_narrative is None
    assert rejected.reviewer_notes == "not accurate, missing context"


def test_original_ai_narrative_never_mutated_by_approve_or_reject():
    """The AI draft must survive review untouched, regardless of outcome —
    this is the audit trail (what did the AI actually say vs. what did a
    human approve)."""
    record = create_pending_review(_sample_narrative_result())
    original_draft = record.ai_narrative

    edited = approve_review(record, edited_text="something totally different")
    assert edited.ai_narrative == original_draft

    rejected = reject_review(record)
    assert rejected.ai_narrative == original_draft


def test_save_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        reviews_dir = Path(tmp)
        record = create_pending_review(_sample_narrative_result())
        save_review(record, reviews_dir=reviews_dir)

        loaded = load_review("apollo_tyres", "FY26", reviews_dir=reviews_dir)
        assert loaded is not None
        assert loaded.company_id == "apollo_tyres"
        assert loaded.status == ReviewStatus.PENDING
        assert len(loaded.flags) == len(record.flags)


def test_load_nonexistent_review_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        result = load_review("nonexistent_company", "FY26", reviews_dir=Path(tmp))
        assert result is None


def test_list_reviews_returns_all_saved():
    with tempfile.TemporaryDirectory() as tmp:
        reviews_dir = Path(tmp)
        record = create_pending_review(_sample_narrative_result())
        save_review(record, reviews_dir=reviews_dir)

        all_reviews = list_reviews(reviews_dir=reviews_dir)
        assert len(all_reviews) == 1
        assert all_reviews[0].company_id == "apollo_tyres"


def test_approving_and_resaving_updates_the_persisted_file():
    with tempfile.TemporaryDirectory() as tmp:
        reviews_dir = Path(tmp)
        record = create_pending_review(_sample_narrative_result())
        save_review(record, reviews_dir=reviews_dir)

        loaded = load_review("apollo_tyres", "FY26", reviews_dir=reviews_dir)
        approved = approve_review(loaded, edited_text=None)
        save_review(approved, reviews_dir=reviews_dir)

        reloaded = load_review("apollo_tyres", "FY26", reviews_dir=reviews_dir)
        assert reloaded.status == ReviewStatus.APPROVED
        assert reloaded.is_final is True
