"""
Financial engine — ratio computation and peer normalization.

- ratios.py computes the derived_ratios defined in config/sectors/<sector>.yaml
  for any FinancialStatement, evaluated against the sector config's formulas.
- peer_table.py assembles a full peer comparison table, pairing each period
  with its prior year for YoY ratios, and flagging basis (standalone vs
  consolidated) mismatches explicitly rather than silently normalizing them.

Anomaly detection itself (statistical/rule-based flagging against these
ratios) is the next module — not built here.
"""

from sentinel.engine.peer_table import build_peer_table, mixed_basis_warning
from sentinel.engine.ratios import compute_ratios

__all__ = ["build_peer_table", "mixed_basis_warning", "compute_ratios"]
