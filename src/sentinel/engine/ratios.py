"""
Computes the derived_ratios defined in config/sectors/<sector>.yaml for a
given FinancialStatement, optionally against a prior-year statement for
YoY formulas.

This is the piece that makes the "config-driven, not hardcoded" claim real
for ratios specifically: nothing in this file knows what "EBITDA margin"
or "YoY PAT growth" means. It only knows how to evaluate a formula string
against a statement's fields. Add a new ratio to tyre.yaml and it shows up
here with zero code changes; point at a different sector's yaml and you
get that sector's ratios instead.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sentinel.schema import FinancialStatement

# Deliberately restricted eval — formulas come from our own config files
# (not user input), but we still strip builtins so a formula can only do
# arithmetic on the fields we hand it, nothing else.
_SAFE_BUILTINS: dict[str, Any] = {}


def _statement_namespace(stmt: FinancialStatement) -> dict[str, Any]:
    """Numeric fields of a statement, keyed by name, for use as eval locals."""
    data = stmt.model_dump()
    return {k: v for k, v in data.items() if isinstance(v, (int, float)) or v is None}


def compute_ratios(
    stmt: FinancialStatement,
    sector_config: dict[str, Any],
    prior_stmt: FinancialStatement | None = None,
) -> dict[str, float | None]:
    """Evaluate every ratio in sector_config['derived_ratios'] for this statement.

    Returns {ratio_id: value}. A ratio whose formula can't be evaluated
    (missing field, prior_stmt is None but formula needs it, division by
    zero) resolves to None rather than raising — a peer table with a gap
    is more useful than a pipeline that crashes on one missing field.
    """
    namespace = _statement_namespace(stmt)
    namespace["prior_year"] = (
        SimpleNamespace(**_statement_namespace(prior_stmt)) if prior_stmt is not None else None
    )

    results: dict[str, float | None] = {}
    for ratio in sector_config.get("derived_ratios", []):
        ratio_id = ratio["id"]
        formula = ratio["formula"]
        try:
            value = eval(formula, {"__builtins__": _SAFE_BUILTINS}, namespace)
            results[ratio_id] = float(value) if value is not None else None
        except (ZeroDivisionError, TypeError, AttributeError, NameError):
            results[ratio_id] = None
    return results
