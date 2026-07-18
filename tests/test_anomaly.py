import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel.anomaly import run_all_checks  # noqa: E402
from sentinel.engine import build_peer_table  # noqa: E402
from sentinel.ingestion import load_all, load_company_config, load_sector_config  # noqa: E402


def _pipeline():
    company_config = load_company_config()
    sector_config = load_sector_config(company_config["sector"])
    statements = load_all()
    fy26 = [s for s in statements if s.period_label == "FY26"]
    peer_df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    return fy26, peer_df, sector_config


def test_apollo_exceptional_item_is_flagged():
    """Apollo's ~44% exceptional-item ratio should trip the 20% threshold —
    this is a real, known finding from the filing, not a made-up case."""
    fy26, peer_df, sector_config = _pipeline()
    flags = run_all_checks(fy26, peer_df, sector_config)
    exceptional_flags = [f for f in flags if f.flag_type == "exceptional_item"]
    assert len(exceptional_flags) == 1
    assert exceptional_flags[0].company_id == "apollo_tyres"
    assert exceptional_flags[0].value > 0.20


def test_balkrishna_yoy_pat_decline_is_flagged():
    fy26, peer_df, sector_config = _pipeline()
    flags = run_all_checks(fy26, peer_df, sector_config)
    balkrishna_flags = [
        f for f in flags if f.company_id == "balkrishna" and f.metric == "yoy_pat_growth"
    ]
    assert len(balkrishna_flags) == 1
    assert balkrishna_flags[0].value < 0


def test_all_five_companies_trip_yoy_pat_swing():
    """FY26 was volatile sector-wide — every company should clear the 15%
    swing threshold on PAT growth, in one direction or the other."""
    fy26, peer_df, sector_config = _pipeline()
    flags = run_all_checks(fy26, peer_df, sector_config)
    pat_swing_companies = {
        f.company_id for f in flags if f.flag_type == "yoy_swing" and f.metric == "yoy_pat_growth"
    }
    assert pat_swing_companies == {"apollo_tyres", "ceat", "jk_tyre", "balkrishna", "mrf"}


def test_thresholds_are_read_from_config_not_hardcoded():
    """Tighten the swing threshold in a copy of the config and confirm the
    flag count changes — proves the detector actually reads the config
    value rather than having a hardcoded 15% somewhere."""
    fy26, peer_df, sector_config = _pipeline()
    baseline_flags = run_all_checks(fy26, peer_df, sector_config)
    baseline_swings = [f for f in baseline_flags if f.flag_type == "yoy_swing"]

    loosened = dict(sector_config)
    loosened["anomaly_thresholds"] = dict(sector_config["anomaly_thresholds"])
    loosened["anomaly_thresholds"]["yoy_swing_pct"] = 60.0  # nothing should clear this

    loosened_flags = run_all_checks(fy26, peer_df, loosened)
    loosened_swings = [f for f in loosened_flags if f.flag_type == "yoy_swing"]

    assert len(loosened_swings) < len(baseline_swings)


def test_peer_outlier_detector_runs_without_error_on_small_n():
    """5-company peer set is a thin sample — the detector should degrade
    gracefully (return fewer/no flags), not crash."""
    fy26, peer_df, sector_config = _pipeline()
    flags = run_all_checks(fy26, peer_df, sector_config)
    # Doesn't assert a specific count — the point is it runs clean on n=5.
    assert isinstance(flags, list)
