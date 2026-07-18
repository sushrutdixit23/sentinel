"""
Turns a company's flags (one or more, same period) into analyst commentary
via a two-turn conversation with Claude — not a single prompt-and-done
call, and not one disconnected call per flag either.

Turn 1: given only the flagged company's own data and ALL of its flags for
         this period, ask for an initial hypothesis. If a company tripped
         two related flags (e.g. a PAT swing AND an outsized exceptional
         item), the model sees both together and can connect them, rather
         than explaining each in isolation and never noticing they're the
         same story.
Turn 2: hand over peer-set context for every flagged metric and ask
         whether that confirms (sector-wide effect), rules out
         (company-specific), or points somewhere else — then give one
         final narrative covering all the flags together.

This is the "agentic reasoning, not single-pass output" requirement from
the foundation doc.

Requires ANTHROPIC_API_KEY (see .env.example).
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import pandas as pd

from sentinel.anomaly.flags import AnomalyFlag
from sentinel.narrative.models import NarrativeResult
from sentinel.schema import FinancialStatement

DEFAULT_MODEL = "claude-sonnet-5"


def _extract_text(response: Any) -> str:
    """Pull the text out of a Claude response.

    Some models return non-text content blocks ahead of the actual text
    (e.g. a thinking block) — content[0] is NOT reliably the text block.
    This scans for the first block with type == "text" instead of
    assuming position.
    """
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise ValueError(
        f"No text block found in response content — got block types: "
        f"{[getattr(b, 'type', type(b).__name__) for b in response.content]}"
    )


class MessagesClient(Protocol):
    """The subset of the Anthropic client's interface this module needs —
    mirrors the real SDK shape (client.messages.create(...)) so a mock
    used in tests looks exactly like the real thing from this module's
    point of view."""

    messages: Any  # has .create(**kwargs) -> object with .content containing a text block


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
        is_ratio = "yoy" in metric or "margin" in metric or "pct" in metric
        formatted = f"{value:+.1%}" if is_ratio else f"{value:,.2f}"
        rows.append(f"  {row['company_name']}: {formatted}{marker}")
    return "\n".join(rows)


def _peer_context_for_metrics(peer_df: pd.DataFrame, metrics: list[str], exclude_company_id: str) -> str:
    """Peer context for every distinct metric across a company's flags,
    each under its own header — not just the first flag's metric."""
    seen: list[str] = []
    sections = []
    for metric in metrics:
        if metric in seen:
            continue
        seen.append(metric)
        sections.append(f"{metric}:\n{_peer_context_for_metric(peer_df, metric, exclude_company_id)}")
    return "\n\n".join(sections)


def group_flags_by_company(flags: list[AnomalyFlag]) -> list[list[AnomalyFlag]]:
    """Group flags by (company_id, period_label) so each group can go
    through generate_narrative() as one bundled call. Preserves the order
    companies first appear in `flags`."""
    groups: dict[tuple[str, str], list[AnomalyFlag]] = {}
    for flag in flags:
        key = (flag.company_id, flag.period_label)
        groups.setdefault(key, []).append(flag)
    return list(groups.values())


def generate_narrative(
    flags: list[AnomalyFlag],
    statements: list[FinancialStatement],
    peer_df: pd.DataFrame,
    sector_config: dict[str, Any],
    client: MessagesClient | None = None,
    model: str = DEFAULT_MODEL,
) -> NarrativeResult:
    """Generate one narrative covering all of `flags`.

    All flags must belong to the same company and period — pass a
    single-item list for a company with only one flag; group multi-flag
    companies before calling this (see scripts/run_narrative.py for the
    grouping helper).
    """
    if not flags:
        raise ValueError("flags cannot be empty")
    company_id = flags[0].company_id
    period_label = flags[0].period_label
    if any(f.company_id != company_id or f.period_label != period_label for f in flags):
        raise ValueError("all flags passed to generate_narrative must share company_id and period_label")

    client = client or _get_client()

    stmt = next(
        s for s in statements if s.company_id == company_id and s.period_label == period_label
    )
    prior = next(
        (
            s
            for s in statements
            if s.company_id == company_id
            and s.period_end_date.year == stmt.period_end_date.year - 1
            and s.period_type == stmt.period_type
        ),
        None,
    )

    system_prompt = (
        f"You are a financial analyst covering the {sector_config['display_name']} sector.\n\n"
        f"{sector_config.get('narrative_context', '')}\n\n"
        "Be concrete and specific. Do not pad with generic caveats. If the data doesn't "
        "support a confident conclusion, say what additional information would resolve it. "
        "If multiple flags are given, consider whether they're connected before treating them "
        "as separate stories."
    )

    flags_block = "\n".join(f"- {f.description}" for f in flags)
    plural = "flags were" if len(flags) > 1 else "flag was"

    turn1_user = (
        f"{len(flags)} {plural} raised for {stmt.company_name} ({period_label}):\n{flags_block}\n\n"
        f"Company data:\n{_company_context(stmt, prior)}\n\n"
        "Based only on this company's own data, what's your initial hypothesis for "
        "why this happened? If there's more than one flag, say whether you think they're "
        "connected or separate issues. 2-4 sentences."
    )
    response1 = client.messages.create(
        model=model,
        max_tokens=500,
        thinking={"type": "disabled"},
        system=system_prompt,
        messages=[{"role": "user", "content": turn1_user}],
    )
    hypothesis = _extract_text(response1)

    metrics = [f.metric for f in flags]
    peer_context = _peer_context_for_metrics(peer_df, metrics, company_id)
    turn2_user = (
        f"Here's how each flagged metric compares across the sector peer set for the same period:\n\n"
        f"{peer_context}\n\n"
        "Does this peer context CONFIRM your hypothesis (a sector-wide effect), RULE IT OUT "
        "(this looks company-specific), or point to something else? State which of the three "
        "explicitly, then give your final analyst narrative in 3-5 sentences covering all the "
        "flags together."
    )
    response2 = client.messages.create(
        model=model,
        max_tokens=700,
        thinking={"type": "disabled"},
        system=system_prompt,
        messages=[
            {"role": "user", "content": turn1_user},
            {"role": "assistant", "content": hypothesis},
            {"role": "user", "content": turn2_user},
        ],
    )
    final_narrative = _extract_text(response2)

    revised = "rule it out" in final_narrative.lower() or "something else" in final_narrative.lower()

    return NarrativeResult(
        company_id=company_id,
        period_label=period_label,
        flags=flags,
        initial_hypothesis=hypothesis,
        peer_context_given=peer_context,
        final_narrative=final_narrative,
        hypothesis_revised=revised,
    )
