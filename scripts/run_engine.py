"""
Runs ingestion + engine end to end: loads all filings, builds the FY26 peer
table with real YoY ratios, and prints it.

Usage:
    python scripts/run_engine.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from sentinel.engine import build_peer_table, mixed_basis_warning  # noqa: E402
from sentinel.ingestion import load_all, load_company_config, load_sector_config  # noqa: E402


def main() -> None:
    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")

    company_config = load_company_config()
    sector_config = load_sector_config(company_config["sector"])
    statements = load_all()

    df = build_peer_table(statements, sector_config, company_config, period_type="FY")

    display_cols = [
        "company_name",
        "basis",
        "revenue_cr",
        "pat_cr",
        "ebitda_margin",
        "pat_margin",
        "yoy_revenue_growth",
        "yoy_pat_growth",
    ]
    pretty = df[display_cols].copy()
    pretty["ebitda_margin"] = pretty["ebitda_margin"].apply(
        lambda x: f"{x:.1%}" if pd.notna(x) else "n/a"
    )
    pretty["pat_margin"] = pretty["pat_margin"].apply(
        lambda x: f"{x:.1%}" if pd.notna(x) else "n/a"
    )
    pretty["yoy_revenue_growth"] = pretty["yoy_revenue_growth"].apply(
        lambda x: f"{x:+.1%}" if pd.notna(x) else "n/a"
    )
    pretty["yoy_pat_growth"] = pretty["yoy_pat_growth"].apply(
        lambda x: f"{x:+.1%}" if pd.notna(x) else "n/a"
    )

    print(f"\nSentinel — FY26 peer table ({sector_config['display_name']})\n")
    print(pretty.to_string(index=False))

    warning = mixed_basis_warning(df)
    if warning:
        print(f"\n⚠ {warning}")

    # Surface anything past the sector's own configured thresholds — reading the
    # threshold, not deciding it; the anomaly module still owns making this a
    # first-class flag.
    swing_threshold = sector_config["anomaly_thresholds"]["yoy_swing_pct"] / 100
    swings = df[df["yoy_pat_growth"].abs() > swing_threshold][["company_name", "yoy_pat_growth"]]
    if not swings.empty:
        print(
            f"\nCompanies past the configured YoY PAT swing threshold "
            f"(±{swing_threshold:.0%}, from tyre.yaml):"
        )
        for _, row in swings.iterrows():
            print(f"  {row['company_name']}: {row['yoy_pat_growth']:+.1%}")


if __name__ == "__main__":
    main()
