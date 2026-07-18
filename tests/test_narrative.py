"""
Tests the narrative module's orchestration logic — message construction,
two-turn flow, context building — with a mocked client. This does NOT
verify the quality of what Claude actually says (that needs a real
ANTHROPIC_API_KEY and a live call, which isn't part of this test suite).
What it does verify: the two-turn structure is real (not a single call
dressed up as two), the peer context excludes/marks the flagged company
correctly, and the result is assembled correctly from both turns.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel.anomaly import run_all_checks  # noqa: E402
from sentinel.engine import build_peer_table  # noqa: E402
from sentinel.ingestion import load_all, load_company_config, load_sector_config  # noqa: E402
from sentinel.narrative import generate_narrative  # noqa: E402


class _FakeResponse:
    def __init__(self, text: str):
        self.content = [SimpleNamespace(text=text)]


class _FakeMessages:
    """Records every call it receives and returns a scripted response per call."""

    def __init__(self, scripted_texts: list[str]):
        self._scripted_texts = scripted_texts
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self._scripted_texts[len(self.calls) - 1]
        return _FakeResponse(text)


class _FakeClient:
    def __init__(self, scripted_texts: list[str]):
        self.messages = _FakeMessages(scripted_texts)


def _pipeline():
    company_config = load_company_config()
    sector_config = load_sector_config(company_config["sector"])
    statements = load_all()
    fy26 = [s for s in statements if s.period_label == "FY26"]
    peer_df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    flags = run_all_checks(fy26, peer_df, sector_config)
    return statements, peer_df, sector_config, flags


def test_two_turns_are_actually_made():
    statements, peer_df, sector_config, flags = _pipeline()
    apollo_flag = next(f for f in flags if f.company_id == "apollo_tyres")

    fake_client = _FakeClient(
        scripted_texts=[
            "Initial hypothesis: likely a one-off restructuring charge.",
            "This RULES IT OUT as sector-wide — no peer shows a comparable exceptional "
            "item this period. Final narrative: company-specific charge.",
        ]
    )

    result = generate_narrative(apollo_flag, statements, peer_df, sector_config, client=fake_client)

    assert len(fake_client.messages.calls) == 2
    # Turn 2 must include turn 1's question AND answer in the message history —
    # otherwise this isn't a real multi-turn check, just two independent calls.
    turn2_messages = fake_client.messages.calls[1]["messages"]
    assert len(turn2_messages) == 3
    assert turn2_messages[1]["role"] == "assistant"
    assert turn2_messages[1]["content"] == "Initial hypothesis: likely a one-off restructuring charge."


def test_flagged_company_marked_in_peer_context_not_excluded():
    """The flagged company should still appear in what Claude sees for turn 2
    (for context/ranking) but marked, not silently dropped."""
    statements, peer_df, sector_config, flags = _pipeline()
    balkrishna_flag = next(
        f for f in flags if f.company_id == "balkrishna" and f.metric == "yoy_pat_growth"
    )
    fake_client = _FakeClient(scripted_texts=["hypothesis text", "final narrative text"])

    result = generate_narrative(
        balkrishna_flag, statements, peer_df, sector_config, client=fake_client
    )

    assert "Balkrishna" in result.peer_context_given
    assert "<- flagged company" in result.peer_context_given


def test_result_assembles_both_turns():
    statements, peer_df, sector_config, flags = _pipeline()
    flag = flags[0]
    fake_client = _FakeClient(scripted_texts=["my hypothesis", "my final narrative"])

    result = generate_narrative(flag, statements, peer_df, sector_config, client=fake_client)

    assert result.initial_hypothesis == "my hypothesis"
    assert result.final_narrative == "my final narrative"
    assert result.flag == flag


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    statements, peer_df, sector_config, flags = _pipeline()

    try:
        generate_narrative(flags[0], statements, peer_df, sector_config, client=None)
        assert False, "expected RuntimeError for missing API key"
    except RuntimeError as e:
        assert "ANTHROPIC_API_KEY" in str(e)
