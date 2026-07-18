"""
Turns an AnomalyFlag into analyst commentary via a two-turn conversation
with Claude — not a single prompt-and-done call.

Turn 1: given only the flagged company's own data, ask for an initial
         hypothesis. The model doesn't see the peer set yet, so it can't
         just describe the peer context back — it has to reason from what
         one company's numbers alone can support.
Turn 2: hand over the same metric across the peer set and ask whether that
         confirms the hypothesis (sector-wide effect), rules it out
         (company-specific), or points somewhere else — then give the
         final narrative.

This is the "agentic reasoning, not single-pass output" requirement from
the foundation doc: the check has to happen against a second data point
before the narrative is finalized, not be assembled from one shot.

Requires ANTHROPIC_API_KEY (see .env.example). Not runnable in the
environment this was built in — verified via a mocked client in
tests/test_narrative.py instead; a live run is the next step for whoever
has a key.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import pandas as pd

from sentinel.anomaly.flags import AnomalyFlag
from sentinel.narrative.models import NarrativeResult
from sentinel.schema import FinancialStatement

DEFAULT_MODEL = "claude-sonnet-5"


class MessagesClient(Protocol):
    """The subset of the Anthropic client's interface this module needs —
    mirrors the real SDK shape (client.messages.create(...)) so a mock
    used in tests looks exactly like the real thing from this module's
    point of view."""

    messages: Any  # has .create(**kwargs) -> object with .content[0].text


def _get_client() -> Any:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key, "
            "or export it directly — see README setup instructions."
        )
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def _company_context(stmt: FinancialStatement, prior: FinancialStatement | None) -> str:
    lines = [
        f"{stmt.company_name} ({stmt.period_label}, {stmt.basis.value}):",
        f"  Revenue: ₹{stmt.revenue_from_operations:,.1f} cr",
        f"  PAT: ₹{stmt.profit_after_tax:,.1f} cr",
        f"  PBT: ₹{stmt.profit_before_tax:,.1f} cr",
    ]
    if stmt.exceptional_items:
        lines.append(f"  Exceptional items: ₹{stmt.exceptional_items:,.1f} cr")
    if prior:
        lines.append(
            f"  Prior year ({prior.period_label}): Revenue ₹{prior.revenue_from_operations:,.1f} cr, "
            f"PAT ₹{prior.profit_after_tax:,.1f} cr"
        )
    return "\n".join(lines)


def _peer_context_for_metric(peer_df: pd.DataFrame, metric: str, exclude_company_id: str) -> str:
    if metric not in peer_df.columns:
        return "(metric not available in peer table)"
    rows = []
    for _, row in peer_df.sort_values(metric, ascending=False).iterrows():
        if pd.isna(row[metric]):
            continue
        marker = " <- flagged company" if row["company_id"] == exclude_company_id else ""
        value = row[metric]
        formatted = f"{value:+.1%}" if "yoy" in metric or "margin" in metric else f"{value:,.2f}"
        rows.append(f"  {row['company_name']}: {formatted}{marker}")
    return "\n".join(rows)


def generate_narrative(
    flag: AnomalyFlag,
    statements: list[FinancialStatement],
    peer_df: pd.DataFrame,
    sector_config: dict[str, Any],
    client: MessagesClient | None = None,
    model: str = DEFAULT_MODEL,
) -> NarrativeResult:
    client = client or _get_client()

    stmt = next(
        s
        for s in statements
        if s.company_id == flag.company_id and s.period_label == flag.period_label
    )
    prior = next(
        (
            s
            for s in statements
            if s.company_id == flag.company_id
            and s.period_end_date.year == stmt.period_end_date.year - 1
            and s.period_type == stmt.period_type
        ),
        None,
    )

    system_prompt = (
        f"You are a financial analyst covering the {sector_config['display_name']} sector.\n\n"
        f"{sector_config.get('narrative_context', '')}\n\n"
        "Be concrete and specific. Do not pad with generic caveats. If the data doesn't "
        "support a confident conclusion, say what additional information would resolve it."
    )

    # Turn 1 — hypothesis from the company's own data only
    turn1_user = (
        f"A flag was raised: {flag.description}\n\n"
        f"Company data:\n{_company_context(stmt, prior)}\n\n"
        "Based only on this company's own data, what's your initial hypothesis for "
        "why this happened? 2-3 sentences."
    )
    response1 = client.messages.create(
        model=model,
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": turn1_user}],
    )
    hypothesis = response1.content[0].text

    # Turn 2 — check the hypothesis against the peer set for the same metric
    peer_context = _peer_context_for_metric(peer_df, flag.metric, flag.company_id)
    turn2_user = (
        f"Here's how {flag.metric} compares across the sector peer set for the same period:\n\n"
        f"{peer_context}\n\n"
        "Does this peer context CONFIRM your hypothesis (a sector-wide effect), RULE IT OUT "
        "(this looks company-specific), or point to something else? State which of the three "
        "explicitly, then give your final analyst narrative in 3-4 sentences."
    )
    response2 = client.messages.create(
        model=model,
        max_tokens=400,
        system=system_prompt,
        messages=[
            {"role": "user", "content": turn1_user},
            {"role": "assistant", "content": hypothesis},
            {"role": "user", "content": turn2_user},
        ],
    )
    final_narrative = response2.content[0].text

    revised = "rule it out" in final_narrative.lower() or "something else" in final_narrative.lower()

    return NarrativeResult(
        flag=flag,
        initial_hypothesis=hypothesis,
        peer_context_given=peer_context,
        final_narrative=final_narrative,
        hypothesis_revised=revised,
    )
