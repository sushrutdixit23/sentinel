"""
The output shape for every anomaly the detector module produces. One flag
per (company, period, metric, reason) — this is what the narrative module
(next, not yet built) will consume and explain in plain language.
"""

from __future__ import annotations

from pydantic import BaseModel


class AnomalyFlag(BaseModel):
    company_id: str
    company_name: str
    period_label: str
    flag_type: str          # "yoy_swing" | "peer_outlier" | "exceptional_item"
    metric: str              # e.g. "yoy_pat_growth", "ebitda_margin"
    value: float              # the actual computed value that triggered the flag
    threshold: float          # the configured threshold it breached
    description: str          # human-readable, built from a template + config, not hardcoded per-company

    def __str__(self) -> str:
        return f"[{self.flag_type}] {self.company_name} ({self.period_label}): {self.description}"
