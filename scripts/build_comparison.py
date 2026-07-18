"""
Runs the ingestion module against data/extracted/ and prints a peer
comparison table. This is the smoke test for the ingestion layer — if this
runs clean, the schema and loader are working end to end.

Usage:
    python scripts/build_comparison.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel.ingestion import load_all, load_company_config  # noqa: E402


def main() -> None:
    companies = load_company_config()
    statements = load_all()

    fy_statements = [s for s in statements if s.period_type.value == "FY"]

    print(f"\nLoaded {len(statements)} filing records ({len(fy_statements)} full-year).\n")
    print(f"Sector: {companies['sector']} | Peer set: {len(companies['companies'])} companies\n")

    header = f"{'Company':<28}{'Basis':<14}{'Revenue (cr)':>14}{'PAT (cr)':>12}{'PAT margin':>12}"
    print(header)
    print("-" * len(header))

    for stmt in sorted(fy_statements, key=lambda s: s.revenue_from_operations, reverse=True):
        margin = f"{stmt.pat_margin:.1%}" if stmt.pat_margin is not None else "n/a"
        print(
            f"{stmt.company_name:<28}{stmt.basis.value:<14}"
            f"{stmt.revenue_from_operations:>14,.1f}{stmt.profit_after_tax:>12,.1f}{margin:>12}"
        )

    print(
        "\nNote: JK Tyre and MRF above are standalone; Apollo and Balkrishna are "
        "consolidated. Not yet apples-to-apples — see README caveat. The engine "
        "module (Tier 2) is where this gets normalized before anomaly detection runs."
    )


if __name__ == "__main__":
    main()
