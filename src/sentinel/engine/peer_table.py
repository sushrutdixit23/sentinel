"""
Builds the peer comparison table: one row per company/period, with every
sector-configured ratio computed, plus explicit basis-comparability flags.

This is the output the anomaly module (Tier 2, next) will consume.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from sentinel.engine.ratios import compute_ratios
from sentinel.schema import FinancialStatement


def _find_prior_year(
    stmt: FinancialStatement, all_statements: list[FinancialStatement]
) -> FinancialStatement | None:
    """Find the same company's statement one full year before this one.

    Matches on company_id + period_type, with period_end_date exactly
    ~1 year earlier. Deliberately strict (not "closest prior period") so a
    quarterly statement never gets silently paired against a full-year one.
    """
    target_year = stmt.period_end_date.year - 1
    for other in all_statements:
        if (
            other.company_id == stmt.company_id
            and other.period_type == stmt.period_type
            and other.period_end_date.year == target_year
            and other.period_end_date.month == stmt.period_end_date.month
        ):
            return other
    return None


def build_peer_table(
    statements: list[FinancialStatement],
    sector_config: dict[str, Any],
    company_config: dict[str, Any],
    period_type: str = "FY",
) -> pd.DataFrame:
    """Build the peer comparison table: each company's MOST RECENT period of
    the given type (default: full year) — not every FY-type record, which
    would otherwise include prior-year comparatives as their own rows.

    Every row is basis-labeled. Rows are NOT silently normalized across
    standalone/consolidated — a `basis_caveat` column flags any company
    whose basis differs from the sector's comparison_basis (the analytical
    standard, e.g. consolidated), so the gap is visible in the table
    rather than hidden by an assumption.
    """
    comparison_basis = {c["id"]: c["comparison_basis"] for c in company_config["companies"]}
    subject_company = next(
        (c["id"] for c in company_config["companies"] if c.get("is_subject")), None
    )

    candidates = [s for s in statements if s.period_type.value == period_type]
    latest_by_company: dict[str, FinancialStatement] = {}
    for s in candidates:
        current = latest_by_company.get(s.company_id)
        if current is None or s.period_end_date > current.period_end_date:
            latest_by_company[s.company_id] = s
    period_statements = list(latest_by_company.values())

    rows = []
    for stmt in period_statements:
        prior = _find_prior_year(stmt, statements)
        ratios = compute_ratios(stmt, sector_config, prior_stmt=prior)

        basis_caveat = None
        expected_basis = comparison_basis.get(stmt.company_id)
        if expected_basis and stmt.basis.value != expected_basis:
            basis_caveat = (
                f"using {stmt.basis.value} — {expected_basis} not available in current extract"
            )

        row = {
            "company_id": stmt.company_id,
            "company_name": stmt.company_name,
            "is_subject": stmt.company_id == subject_company,
            "period_label": stmt.period_label,
            "basis": stmt.basis.value,
            "basis_caveat": basis_caveat,
            "revenue_cr": stmt.revenue_from_operations,
            "pat_cr": stmt.profit_after_tax,
            "pbt_cr": stmt.profit_before_tax,
            "exceptional_items_cr": stmt.exceptional_items,
            "has_prior_year": prior is not None,
            **ratios,
        }
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("revenue_cr", ascending=False).reset_index(drop=True)
    return df


def mixed_basis_warning(df: pd.DataFrame) -> str | None:
    """One-line warning if the table mixes standalone and consolidated bases.

    Margin ratios (EBITDA margin, PAT margin) are reasonably comparable
    across basis since both numerator and denominator scale together.
    Absolute figures (revenue_cr, pat_cr) are NOT — a consolidated
    Apollo vs. standalone MRF comparison on absolute PAT is comparing
    different things. This function doesn't decide for the caller; it
    just makes sure the gap can't be missed.
    """
    bases = set(df["basis"].unique())
    if len(bases) <= 1:
        return None
    flagged = df[df["basis_caveat"].notna()]["company_name"].tolist()
    return (
        f"Mixed basis in this table ({', '.join(sorted(bases))}). "
        f"Absolute figures (revenue_cr, pat_cr) are not directly comparable "
        f"across rows. Margin ratios are more comparable but not guaranteed "
        f"equivalent. Affected: {', '.join(flagged)}."
    )
