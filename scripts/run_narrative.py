"""
Full pipeline: ingestion -> engine -> anomaly -> narrative.

Requires ANTHROPIC_API_KEY (see .env.example). This is the one script in
this repo that costs real API tokens to run — it makes 2 calls per flag.

Usage:
    cp .env.example .env   # then fill in your key
    python scripts/run_narrative.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from sentinel.anomaly import run_all_checks  # noqa: E402
from sentinel.engine import build_peer_table  # noqa: E402
from sentinel.ingestion import load_all, load_company_config, load_sector_config  # noqa: E402
from sentinel.narrative import generate_narrative, group_flags_by_company  # noqa: E402


def main() -> None:
    company_config = load_company_config()
    sector_config = load_sector_config(company_config["sector"])
    statements = load_all()

    fy26_statements = [s for s in statements if s.period_label == "FY26"]
    peer_df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    flags = run_all_checks(fy26_statements, peer_df, sector_config)
    groups = group_flags_by_company(flags)

    print(f"\n{len(flags)} flags across {len(groups)} companies. Making 2 API calls per company...\n")

    for group in groups:
        company_name = group[0].company_name
        print("=" * 78)
        print(f"{company_name} ({group[0].period_label}) — {len(group)} flag(s)")
        for f in group:
            print(f"  - {f}")
        print("=" * 78)
        result = generate_narrative(group, statements, peer_df, sector_config)
        print(f"\n[Turn 1 — hypothesis from own data]\n{result.initial_hypothesis}\n")
        print(f"[Turn 2 — checked against peer set, final narrative]\n{result.final_narrative}\n")


if __name__ == "__main__":
    main()
