import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from sentinel.ingestion import load_all, load_company_config, load_sector_config  # noqa: E402
from sentinel.schema import Basis, PeriodType  # noqa: E402


def test_companies_config_loads():
    config = load_company_config()
    assert config["sector"] == "tyre"
    ids = {c["id"] for c in config["companies"]}
    assert ids == {"apollo_tyres", "ceat", "jk_tyre", "balkrishna", "mrf"}


def test_sector_config_loads():
    config = load_sector_config("tyre")
    assert config["sector_id"] == "tyre"
    assert "anomaly_thresholds" in config


def test_sector_config_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_sector_config("nonexistent_sector")


def test_load_all_returns_validated_statements():
    statements = load_all()
    assert len(statements) >= 14  # 5 companies x (FY26 + FY25) + 4 Balkrishna quarters
    for stmt in statements:
        assert stmt.revenue_from_operations > 0
        assert stmt.company_id
        assert stmt.source_file


def test_all_five_companies_have_fy26_data():
    statements = load_all()
    fy26 = {s.company_id for s in statements if s.period_label == "FY26"}
    assert fy26 == {"apollo_tyres", "ceat", "jk_tyre", "balkrishna", "mrf"}


def test_balkrishna_quarterly_sums_to_annual():
    """Real cross-check: the four quarterly PATs should sum to the FY total.
    This caught nothing wrong here, but it's the kind of check that would
    catch a transcription error in a future extraction.
    """
    statements = load_all()
    balkrishna = [s for s in statements if s.company_id == "balkrishna"]
    quarters = [s for s in balkrishna if s.period_type != PeriodType.FY]
    annual = next(
        s for s in balkrishna if s.period_type == PeriodType.FY and s.period_label == "FY26"
    )

    assert len(quarters) == 4
    quarterly_sum = sum(q.profit_after_tax for q in quarters)
    assert quarterly_sum == pytest.approx(annual.profit_after_tax, abs=0.5)


def test_basis_is_flagged_correctly():
    statements = load_all()
    by_id = {s.company_id: s for s in statements if s.period_label == "FY26"}
    assert by_id["apollo_tyres"].basis == Basis.CONSOLIDATED
    assert by_id["balkrishna"].basis == Basis.CONSOLIDATED
    assert by_id["jk_tyre"].basis == Basis.STANDALONE
    assert by_id["mrf"].basis == Basis.STANDALONE
