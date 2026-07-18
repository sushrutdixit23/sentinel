"""
Tests the narrative module's orchestration logic — message construction,
two-turn flow, flag-bundling-by-company, context building — with a mocked
client. This does NOT verify the quality of what Claude actually says
(that needs a real ANTHROPIC_API_KEY and a live call). What it does
verify: the two-turn structure is real, flags for the same company are
bundled into one call instead of narrated separately, the peer context
covers every flagged metric, and results assemble correctly.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel.anomaly import run_all_checks  # noqa: E402
from sentinel.engine import build_peer_table  # noqa: E402
from sentinel.ingestion import load_all, load_company_config, load_sector_config  # noqa: E402
from sentinel.narrative import generate_narrative, group_flags_by_company  # noqa: E402


class _FakeResponse:
    def __init__(self, text: str, with_thinking_block: bool = False):
        content = []
        if with_thinking_block:
            content.append(SimpleNamespace(type="thinking", thinking="reasoning..."))
        content.append(SimpleNamespace(type="text", text=text))
        self.content = content


class _FakeMessages:
    def __init__(self, scripted_texts: list[str], with_thinking_blocks: bool = False):
        self._scripted_texts = scripted_texts
        self._with_thinking_blocks = with_thinking_blocks
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self._scripted_texts[len(self.calls) - 1]
        return _FakeResponse(text, with_thinking_block=self._with_thinking_blocks)


class _FakeClient:
    def __init__(self, scripted_texts: list[str], with_thinking_blocks: bool = False):
        self.messages = _FakeMessages(scripted_texts, with_thinking_blocks=with_thinking_blocks)


def _pipeline():
    company_config = load_company_config()
    sector_config = load_sector_config(company_config["sector"])
    statements = load_all()
    fy26 = [s for s in statements if s.period_label == "FY26"]
    peer_df = build_peer_table(statements, sector_config, company_config, period_type="FY")
    flags = run_all_checks(fy26, peer_df, sector_config)
    return statements, peer_df, sector_config, flags


def test_apollo_has_two_flags_that_get_grouped_together():
    """Regression case for the real gap found live: Apollo trips both a
    yoy_swing and an exceptional_item flag. They must end up in the same
    group, not narrated as two disconnected calls."""
    _, _, _, flags = _pipeline()
    groups = group_flags_by_company(flags)
    apollo_group = next(g for g in groups if g[0].company_id == "apollo_tyres")
    assert len(apollo_group) == 2
    assert {f.flag_type for f in apollo_group} == {"yoy_swing", "exceptional_item"}


def test_group_flags_by_company_covers_every_flag_exactly_once():
    _, _, _, flags = _pipeline()
    groups = group_flags_by_company(flags)
    regrouped = [f for g in groups for f in g]
    assert len(regrouped) == len(flags)


def test_two_turns_are_actually_made():
    statements, peer_df, sector_config, flags = _pipeline()
    groups = group_flags_by_company(flags)
    apollo_group = next(g for g in groups if g[0].company_id == "apollo_tyres")

    fake_client = _FakeClient(
        scripted_texts=[
            "Initial hypothesis: the swing and the exceptional item are the same story.",
            "This RULES IT OUT as sector-wide. Final narrative: company-specific charge "
            "explains both flags together.",
        ]
    )

    generate_narrative(apollo_group, statements, peer_df, sector_config, client=fake_client)

    assert len(fake_client.messages.calls) == 2
    turn2_messages = fake_client.messages.calls[1]["messages"]
    assert len(turn2_messages) == 3
    assert turn2_messages[1]["role"] == "assistant"
    assert turn2_messages[1]["content"] == (
        "Initial hypothesis: the swing and the exceptional item are the same story."
    )


def test_bundled_flags_both_appear_in_turn1_prompt():
    """The actual bundling fix: both of Apollo's flag descriptions must be
    visible to the model in the same turn-1 message, not split across
    separate calls."""
    statements, peer_df, sector_config, flags = _pipeline()
    groups = group_flags_by_company(flags)
    apollo_group = next(g for g in groups if g[0].company_id == "apollo_tyres")
    fake_client = _FakeClient(scripted_texts=["hyp", "final"])

    generate_narrative(apollo_group, statements, peer_df, sector_config, client=fake_client)

    turn1_content = fake_client.messages.calls[0]["messages"][0]["content"]
    for flag in apollo_group:
        assert flag.description in turn1_content


def test_peer_context_covers_every_flagged_metric_not_just_the_first():
    statements, peer_df, sector_config, flags = _pipeline()
    groups = group_flags_by_company(flags)
    apollo_group = next(g for g in groups if g[0].company_id == "apollo_tyres")
    fake_client = _FakeClient(scripted_texts=["hyp", "final"])

    result = generate_narrative(apollo_group, statements, peer_df, sector_config, client=fake_client)

    metrics = {f.metric for f in apollo_group}
    for metric in metrics:
        assert metric in result.peer_context_given
    # the exceptional-item metric specifically must have real peer data now,
    # not the "(metric not available in peer table)" fallback
    assert "not available" not in result.peer_context_given


def test_single_flag_company_still_works():
    statements, peer_df, sector_config, flags = _pipeline()
    groups = group_flags_by_company(flags)
    single_flag_group = next(g for g in groups if len(g) == 1)
    fake_client = _FakeClient(scripted_texts=["hyp", "final"])

    result = generate_narrative(single_flag_group, statements, peer_df, sector_config, client=fake_client)

    assert len(result.flags) == 1
    assert result.final_narrative == "final"


def test_flags_from_different_companies_rejected():
    statements, peer_df, sector_config, flags = _pipeline()
    mismatched = [flags[0], next(f for f in flags if f.company_id != flags[0].company_id)]
    fake_client = _FakeClient(scripted_texts=["hyp", "final"])

    try:
        generate_narrative(mismatched, statements, peer_df, sector_config, client=fake_client)
        assert False, "expected ValueError for mismatched company_id flags"
    except ValueError as e:
        assert "company_id" in str(e)


def test_result_assembles_both_turns():
    statements, peer_df, sector_config, flags = _pipeline()
    single_flag_group = [flags[0]]
    fake_client = _FakeClient(scripted_texts=["my hypothesis", "my final narrative"])

    result = generate_narrative(single_flag_group, statements, peer_df, sector_config, client=fake_client)

    assert result.initial_hypothesis == "my hypothesis"
    assert result.final_narrative == "my final narrative"
    assert result.flags == single_flag_group


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    statements, peer_df, sector_config, flags = _pipeline()

    try:
        generate_narrative([flags[0]], statements, peer_df, sector_config, client=None)
        assert False, "expected RuntimeError for missing API key"
    except RuntimeError as e:
        assert "ANTHROPIC_API_KEY" in str(e)


def test_handles_thinking_block_ahead_of_text_block():
    """Regression test: Claude Sonnet 5 returns a thinking block before the
    text block by default. content[0] is NOT reliably the text — this hit
    a real user running scripts/run_narrative.py live."""
    statements, peer_df, sector_config, flags = _pipeline()
    fake_client = _FakeClient(
        scripted_texts=["hypothesis despite thinking block", "final narrative despite thinking block"],
        with_thinking_blocks=True,
    )

    result = generate_narrative([flags[0]], statements, peer_df, sector_config, client=fake_client)

    assert result.initial_hypothesis == "hypothesis despite thinking block"
    assert result.final_narrative == "final narrative despite thinking block"


def test_thinking_is_explicitly_disabled_in_both_calls():
    """Regression test for a second live failure: with thinking left on,
    adaptive thinking can consume the entire max_tokens budget before any
    visible text is written — this hit a real user on the MRF flag."""
    statements, peer_df, sector_config, flags = _pipeline()
    fake_client = _FakeClient(scripted_texts=["hyp", "final"])

    generate_narrative([flags[0]], statements, peer_df, sector_config, client=fake_client)

    for call in fake_client.messages.calls:
        assert call.get("thinking") == {"type": "disabled"}
