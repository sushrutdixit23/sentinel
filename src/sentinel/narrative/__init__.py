"""
Narrative generation — Claude-generated analyst commentary.

Two-turn agentic pattern per flag: hypothesis from the company's own data
first, then a check against the peer set before finalizing — see
generator.py for why this isn't a single prompt-and-done call.

Requires ANTHROPIC_API_KEY. See .env.example and README setup.
"""

from sentinel.narrative.generator import generate_narrative, group_flags_by_company
from sentinel.narrative.models import NarrativeResult

__all__ = ["generate_narrative", "group_flags_by_company", "NarrativeResult"]
