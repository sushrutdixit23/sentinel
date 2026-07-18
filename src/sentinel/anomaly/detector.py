"""
Three detectors, all driven by config/sectors/<sector>.yaml's
anomaly_thresholds — nothing here hardcodes a number or a company name.

1. YoY swing — flags a company whose yoy_revenue_growth or yoy_pat_growth
   (already computed by the engine module) exceeds the configured swing.
2. Peer-relative outlier — z-scores a company's ratio against the peer
   set's own mean/std for that period.
3. Exceptional item — flags when exceptional items make up an outsized
   share of pre-exceptional profit.

Each returns a list[AnomalyFlag]; run_all_checks() combines them.
"""

from __future__ import annotations

import statistics
from typing import Any

import pandas as pd

from sentinel.anomaly.flags import AnomalyFlag
from sentinel.schema import FinancialStatement

# Ratios checked for peer-relative outliers. Deliberately a fixed list here
# rather than "every column in the peer table" — z-scoring a growth ratio
# against a same-period peer set conflates two different questions (this
# vs. last year, and this company vs. its peers), so we keep it to
# point-in-time margin ratios where a peer z-score is a clean comparison.
_PEER_RELATIVE_METRICS = ["ebitda_margin", "pat_margin"]


def detect_yoy_swings(df: pd.DataFrame, sector_config: dict[str, Any]) -> list[AnomalyFlag]:
    threshold_pct = sector_config["anomaly_thresholds"]["yoy_swing_pct"]
    threshold = threshold_pct / 100
    flags = []

    for metric in ("yoy_revenue_growth", "yoy_pat_growth"):
        if metric not in df.columns:
            continue
        for _, row in df.iterrows():
            value = row[metric]
            if pd.isna(value) or abs(value) <= threshold:
                continue
            direction = "grew" if value > 0 else "declined"
            flags.append(
                AnomalyFlag(
                    company_id=row["company_id"],
                    company_name=row["company_name"],
                    period_label=row["period_label"],
                    flag_type="yoy_swing",
                    metric=metric,
                    value=float(value),
                    threshold=threshold,
                    description=(
                        f"{metric.replace('yoy_', '').replace('_', ' ')} {direction} "
                        f"{abs(value):.1%} YoY, past the configured ±{threshold_pct:.0f}% swing threshold"
                    ),
                )
            )
    return flags


def detect_peer_relative_outliers(
    df: pd.DataFrame, sector_config: dict[str, Any]
) -> list[AnomalyFlag]:
    """Z-score each company's ratio against the peer set's own distribution.

    Caveat worth being honest about: with a 5-company peer set, a
    population standard deviation is a thin statistical basis — one or two
    companies can swing the mean and std considerably. This is fine for a
    "worth a second look" flag, not for a claim of statistical
    significance. That distinction belongs in the narrative layer, not
    silently baked into this threshold.
    """
    z_threshold = sector_config["anomaly_thresholds"]["peer_relative_zscore"]
    flags = []

    for metric in _PEER_RELATIVE_METRICS:
        if metric not in df.columns:
            continue
        values = df[metric].dropna()
        if len(values) < 3:
            continue  # not enough peers for a meaningful spread
        mean = statistics.mean(values)
        stdev = statistics.pstdev(values)
        if stdev == 0:
            continue

        for _, row in df.iterrows():
            value = row[metric]
            if pd.isna(value):
                continue
            z = (value - mean) / stdev
            if abs(z) <= z_threshold:
                continue
            direction = "above" if z > 0 else "below"
            flags.append(
                AnomalyFlag(
                    company_id=row["company_id"],
                    company_name=row["company_name"],
                    period_label=row["period_label"],
                    flag_type="peer_outlier",
                    metric=metric,
                    value=float(value),
                    threshold=z_threshold,
                    description=(
                        f"{metric.replace('_', ' ')} of {value:.1%} is {abs(z):.1f} std dev "
                        f"{direction} the {len(values)}-company peer mean of {mean:.1%} "
                        f"(n={len(values)} — small sample, treat as a lead not a verdict)"
                    ),
                )
            )
    return flags


def detect_exceptional_items(
    statements: list[FinancialStatement], sector_config: dict[str, Any]
) -> list[AnomalyFlag]:
    threshold_pct = sector_config["anomaly_thresholds"]["exceptional_item_pct_of_pbt"]
    threshold = threshold_pct / 100
    flags = []

    for stmt in statements:
        if not stmt.exceptional_items:
            continue
        pre_exceptional_pbt = stmt.profit_before_tax + stmt.exceptional_items
        if pre_exceptional_pbt <= 0:
            continue  # ratio isn't meaningful against a pre-exceptional loss
        ratio = stmt.exceptional_items / pre_exceptional_pbt
        if ratio <= threshold:
            continue
        flags.append(
            AnomalyFlag(
                company_id=stmt.company_id,
                company_name=stmt.company_name,
                period_label=stmt.period_label,
                flag_type="exceptional_item",
                metric="exceptional_item_pct_of_pbt",
                value=ratio,
                threshold=threshold,
                description=(
                    f"exceptional items (₹{stmt.exceptional_items:,.1f} cr) are "
                    f"{ratio:.1%} of pre-exceptional PBT (₹{pre_exceptional_pbt:,.1f} cr), "
                    f"past the configured {threshold_pct:.0f}% threshold"
                ),
            )
        )
    return flags


def run_all_checks(
    statements: list[FinancialStatement],
    peer_df: pd.DataFrame,
    sector_config: dict[str, Any],
) -> list[AnomalyFlag]:
    """Run every detector and return the combined, unsorted flag list."""
    flags: list[AnomalyFlag] = []
    flags += detect_yoy_swings(peer_df, sector_config)
    flags += detect_peer_relative_outliers(peer_df, sector_config)
    flags += detect_exceptional_items(statements, sector_config)
    return flags
