"""
The normalized shape every company's filing data gets forced into.

This is the contract between ingestion and everything downstream. A filing
from Apollo Tyres (reported in ₹ Million) and a filing from Balkrishna
(reported in ₹ Crore) both end up as a FinancialStatement with the same
fields, in the same unit, so the engine layer never needs to know which
company or sector it's looking at.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Basis(str, Enum):
    STANDALONE = "standalone"
    CONSOLIDATED = "consolidated"


class PeriodType(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    FY = "FY"  # full year


class FinancialStatement(BaseModel):
    """One company, one reporting period, one basis (standalone/consolidated).

    All monetary fields are normalized to INR crore regardless of how the
    source filing reported them (Apollo reports in ₹ Million, most peers in
    ₹ Crore — the ingestion loader does the conversion before this object
    is constructed, never the caller).
    """

    company_id: str = Field(..., description="Matches an id in config/companies.yaml")
    company_name: str
    ticker: str

    period_type: PeriodType
    period_label: str = Field(..., description='e.g. "FY26", "Q4 FY26"')
    period_end_date: date
    basis: Basis

    currency_unit: str = Field(default="INR_CRORE")

    # Core P&L — all in INR crore
    revenue_from_operations: float
    other_income: Optional[float] = None
    total_income: Optional[float] = None
    total_expenses: Optional[float] = None
    ebitda: Optional[float] = None
    depreciation_amortisation: Optional[float] = None
    finance_costs: Optional[float] = None
    exceptional_items: Optional[float] = Field(
        default=0.0, description="Positive = expense/loss recognized"
    )
    profit_before_tax: float
    tax_expense: Optional[float] = None
    profit_after_tax: float

    # Provenance — every number traces back to a real filing
    source_file: str
    source_page: Optional[str] = None
    extraction_notes: Optional[str] = None

    @field_validator("period_label")
    @classmethod
    def _label_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("period_label cannot be empty")
        return v

    @property
    def ebitda_margin(self) -> Optional[float]:
        if self.ebitda is None or self.revenue_from_operations == 0:
            return None
        return self.ebitda / self.revenue_from_operations

    @property
    def pat_margin(self) -> Optional[float]:
        if self.revenue_from_operations == 0:
            return None
        return self.profit_after_tax / self.revenue_from_operations
