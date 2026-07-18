import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from sentinel.engine import build_peer_table, compute_ratios, mixed_basis_warning  # noqa: E402
from sentinel.ingestion import load_all, load_company_config, load_sector_config  # noqa: E402


def _setup():
    company_config = load_company_config()
    sector_config = load_sector_config(company_config["sector"])
    statements = load_all()
    return company_config, sector_config, statements


def test_compute_ratios_basic_margin():
    _, sector_config, statements = _setup()
    apollo_fy26 = next(
        s for s in statements if s.company_id == "apollo_tyres" and s.period_label == "FY26"
    )
    ratios = compute_ratios(apollo_fy26, sector_config)
    assert ratios["ebitda_margin"] is not None
    assert 0.10 < ratios["ebitda_margin"] < 0.20  # sanity range for this sector


def test_compute_ratios_yoy_needs_prior_year():
    _, sector_config, statements = _setup()
    apollo_fy26 = next(
        s for s in statements if s.company_id == "apollo_tyres" and s.period_label == "FY26"
    )
    apollo_fy25 = next(
        s for s in statements if s.company_id == "apollo_tyres" and s.period_label == "FY25"
    )
    ratios_no_prior = compute_ratios(apollo_fy26, sector_config, prior_stmt=None)
    ratios_with_prior = compute_ratios(apollo_fy26, sector_config, prior_stmt=apollo_fy25)

    expected = (
        apollo_fy26.revenue_from_operations - apollo_fy25.revenue_from_operations
    ) / apollo_fy25.revenue_from_operations

    assert ratios_no_prior["yoy_revenue_growth"] is None
    assert ratios_with_prior["yoy_revenue_growth"] is not None
    assert abs(ratios_with_prior["yoy_revenue_growth"] - expected) < 1e-9


def test_build_peer_table_one_row_per_company():
    company_config, sector_config, statements = _setup()
    df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    assert len(df) == 5
    assert set(df["company_name"]) == {
        "Apollo Tyres Ltd",
        "Ceat Ltd",
        "JK Tyre & Industries Ltd",
        "Balkrishna Industries Ltd",
        "MRF Ltd",
    }


def test_build_peer_table_excludes_prior_year_as_own_row():
    """Regression test: FY25 comparatives must feed yoy_* ratios, not appear
    as separate rows in the peer table (this was a real bug caught by
    actually running the script — see conversation)."""
    company_config, sector_config, statements = _setup()
    df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    assert set(df["period_label"]) == {"FY26"}


def test_build_peer_table_flags_basis_caveat_for_standalone_only_companies():
    company_config, sector_config, statements = _setup()
    df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    by_id = df.set_index("company_id")
    assert pd.notna(by_id.loc["mrf", "basis_caveat"])
    assert pd.notna(by_id.loc["jk_tyre", "basis_caveat"])
    assert pd.isna(by_id.loc["apollo_tyres", "basis_caveat"])
    assert pd.isna(by_id.loc["balkrishna", "basis_caveat"])


def test_mixed_basis_warning_fires_and_names_affected_companies():
    company_config, sector_config, statements = _setup()
    df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    warning = mixed_basis_warning(df)
    assert warning is not None
    assert "MRF Ltd" in warning
    assert "JK Tyre" in warning


def test_balkrishna_pat_decline_is_visible_in_yoy_ratio():
    """The real finding from the foundation doc: Balkrishna's PAT fell
    while every peer grew. Confirms the engine surfaces it correctly,
    not just that the loader can read the raw figures."""
    company_config, sector_config, statements = _setup()
    df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    balkrishna_growth = df.set_index("company_id").loc["balkrishna", "yoy_pat_growth"]
    assert balkrishna_growth < 0
    other_growths = df[df["company_id"] != "balkrishna"]["yoy_pat_growth"]
    assert (other_growths > 0).all()
