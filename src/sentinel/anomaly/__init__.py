"""
Anomaly detection — peer-relative and historical variance flagging.

Three detectors, all reading their thresholds from
config/sectors/<sector>.yaml (anomaly_thresholds) rather than hardcoding
any number:

- detect_yoy_swings: flags YoY revenue/PAT growth past a configured swing
- detect_peer_relative_outliers: z-scores margin ratios against the peer set
- detect_exceptional_items: flags outsized exceptional items vs. pre-exceptional PBT

run_all_checks() combines all three into one flag list. The narrative
module (next, not yet built) is what turns these flags into an explained,
agentic writeup — this module only decides WHAT to flag, not why it
happened.
"""

from sentinel.anomaly.detector import (
    detect_exceptional_items,
    detect_peer_relative_outliers,
    detect_yoy_swings,
    run_all_checks,
)
from sentinel.anomaly.flags import AnomalyFlag

__all__ = [
    "AnomalyFlag",
    "detect_yoy_swings",
    "detect_peer_relative_outliers",
    "detect_exceptional_items",
    "run_all_checks",
]
