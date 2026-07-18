"""
Loads config/ and data/extracted/ into validated, in-memory objects.

This is the only place in the codebase that touches raw YAML/JSON files.
Everything downstream (engine, anomaly, narrative) works with
FinancialStatement objects and plain dicts from the config loaders — never
with file paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from sentinel.schema import FinancialStatement

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "extracted"


def load_company_config(path: Path | None = None) -> dict[str, Any]:
    """Load config/companies.yaml — the peer set definition."""
    path = path or DEFAULT_CONFIG_DIR / "companies.yaml"
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_sector_config(sector_id: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Load config/sectors/<sector_id>.yaml — the swappable sector rules layer.

    This is the function that makes Sentinel sector-agnostic: point it at
    "tyre", "epc", or any other sector_id with a matching config file, and
    every downstream consumer of this config gets the right rules without
    any code change.
    """
    config_dir = config_dir or DEFAULT_CONFIG_DIR / "sectors"
    path = config_dir / f"{sector_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No sector config found for '{sector_id}' at {path}. "
            f"Available: {[p.stem for p in config_dir.glob('*.yaml')]}"
        )
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_statement(json_path: Path) -> FinancialStatement:
    """Load and validate a single extracted filing record."""
    with open(json_path, "r") as f:
        raw = json.load(f)
    try:
        return FinancialStatement.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"Schema validation failed for {json_path.name}: {e}") from e


def load_all(data_dir: Path | None = None) -> list[FinancialStatement]:
    """Load every extracted filing record in data/extracted/.

    Runs each one through schema validation and a set of internal
    consistency checks (see _sanity_check). A record that fails schema
    validation raises immediately — bad data shouldn't silently enter the
    pipeline. A record that fails a sanity check is loaded but flagged via
    a printed warning, since these are often genuine filing nuances (e.g.
    Apollo's negative tax expense) rather than extraction errors.
    """
    data_dir = data_dir or DEFAULT_DATA_DIR
    statements = []
    for json_path in sorted(data_dir.glob("*.json")):
        stmt = load_statement(json_path)
        for warning in _sanity_check(stmt):
            print(f"[sanity-check] {json_path.name}: {warning}")
        statements.append(stmt)
    return statements


def _sanity_check(stmt: FinancialStatement) -> list[str]:
    """Internal consistency checks — not the anomaly module.

    These catch extraction/transcription errors (a misplaced decimal, a
    unit conversion mistake) before bad data reaches the engine layer.
    They are deliberately loose — a genuine filing can trip these (see
    Apollo's tax credit) and that's fine, it just gets a printed note.
    """
    warnings: list[str] = []
    tol = 0.02  # 2% tolerance for rounding across a multi-line P&L

    if stmt.total_income is not None and stmt.other_income is not None:
        expected = stmt.revenue_from_operations + stmt.other_income
        if abs(expected - stmt.total_income) > abs(expected) * tol:
            warnings.append(
                f"total_income ({stmt.total_income}) doesn't reconcile with "
                f"revenue + other_income ({expected:.2f})"
            )

    if stmt.tax_expense is not None:
        expected_pat = stmt.profit_before_tax - stmt.tax_expense
        if abs(expected_pat - stmt.profit_after_tax) > abs(expected_pat) * tol:
            warnings.append(
                f"profit_after_tax ({stmt.profit_after_tax}) doesn't reconcile "
                f"with PBT - tax ({expected_pat:.2f})"
            )

    if stmt.profit_before_tax < 0 or stmt.profit_after_tax < 0:
        warnings.append("negative PBT or PAT — confirm this isn't an extraction sign error")

    return warnings
