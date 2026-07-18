"""
Full pipeline so far: ingestion -> engine -> anomaly.

Usage:
    python scripts/run_anomaly.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel.anomaly import run_all_checks  # noqa: E402
from sentinel.engine import build_peer_table  # noqa: E402
from sentinel.ingestion import load_all, load_company_config, load_sector_config  # noqa: E402


def main() -> None:
    company_config = load_company_config()
    sector_config = load_sector_config(company_config["sector"])
    statements = load_all()

    fy26_statements = [s for s in statements if s.period_label == "FY26"]
    peer_df = build_peer_table(statements, sector_config, company_config, period_type="FY")

    flags = run_all_checks(fy26_statements, peer_df, sector_config)

    print(f"\nSentinel — anomaly flags, FY26 ({sector_config['display_name']} peer set)\n")
    print(f"{len(flags)} flags across {len(fy26_statements)} companies.\n")

    by_type: dict[str, list] = {}
    for flag in flags:
        by_type.setdefault(flag.flag_type, []).append(flag)

    for flag_type, group in by_type.items():
        print(f"── {flag_type} ({len(group)}) " + "─" * (40 - len(flag_type)))
        for flag in sorted(group, key=lambda f: abs(f.value), reverse=True):
            print(f"  {flag}")
        print()

    if not flags:
        print("No flags — thresholds in config/sectors/tyre.yaml may need tuning,")
        print("or this peer set genuinely had a quiet year (it didn't — check the engine output).")


if __name__ == "__main__":
    main()
