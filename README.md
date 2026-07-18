# Sentinel

An AI agent that ingests public company filings and produces analyst-grade
financial commentary — variance detection, peer benchmarking, and narrative
reasoning, without a human analyst in the loop.

This is Tier 1/2 of the Sentinel build: Apollo Tyres benchmarked against its
tyre-sector peer set (Ceat, JK Tyre, Balkrishna Industries, MRF), using real
FY26 (year ended March 31, 2026) filings.

## Architecture principle

Nothing about this pipeline is tyre-specific in code. Sector knowledge —
which line items matter, what counts as an anomaly, who the peers are —
lives entirely in `config/`. The pipeline underneath (`src/sentinel/`) is
generic: point it at a different `config/sectors/*.yaml` and a different
`data/extracted/` set, and it works for any industry.

```
config/companies.yaml         → who's in the peer set
config/sectors/tyre.yaml      → sector-specific rules and thresholds
data/extracted/*.json         → normalized filing data (one file per company/period)
src/sentinel/schema.py        → the common shape every company's data is forced into
src/sentinel/ingestion/       → loads + validates data/extracted/ against schema.py
src/sentinel/engine/          → ratio and variance computation (Tier 2)
src/sentinel/anomaly/         → peer-relative + historical anomaly detection (Tier 2)
src/sentinel/narrative/       → Claude-generated analyst commentary (Tier 2)
```

## Status

- [x] Repo structure + config layer
- [x] Ingestion module — loads and validates real FY26 + FY25 filings for all 5 companies
- [x] Financial engine — ratio computation (`engine/ratios.py`), peer table with
      explicit basis-comparability flags (`engine/peer_table.py`)
- [x] Anomaly module — YoY swing, peer-relative z-score, and exceptional-item
      detectors (`anomaly/detector.py`), all threshold-driven from
      `config/sectors/tyre.yaml`
- [x] Narrative layer — two-turn agentic pattern (hypothesis from own data,
      then checked against peer context) in `narrative/generator.py`.
      **Built and tested against a mocked client, not yet run live** — needs
      your own `ANTHROPIC_API_KEY` (see `.env.example`). Everything else in
      this repo has been executed end-to-end against the real filing data;
      this module is the one exception, by necessity.
- [ ] Dashboard (Streamlit)

Run `python scripts/run_anomaly.py` for the full pipeline through anomaly
detection (no API key needed). Run `python scripts/run_narrative.py` for
the narrative layer on top — this one costs real tokens (2 calls per flag,
7 flags on the current FY26 dataset = 14 calls).

## Data provenance

Every number in `data/extracted/` traces back to a real, public filing —
annual reports and investor presentations pulled directly from each
company's investor relations page. See `source_file` and `source_page`
in each JSON record. No synthetic data anywhere in this pipeline.

**Known inconsistency to resolve in the engine layer:** Apollo Tyres and
Balkrishna Industries figures below are consolidated; JK Tyre and MRF are
standalone (their consolidated breakouts weren't in the pulled filing
sections). This is flagged, not silently normalized — the engine layer
needs to either source the missing consolidated figures or explicitly
model basis (standalone vs consolidated) as a comparability caveat.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python scripts/build_comparison.py   # ingestion only
python scripts/run_engine.py         # + ratio engine
python scripts/run_anomaly.py        # + anomaly flags — no API key needed for any of the above

cp .env.example .env                 # add your ANTHROPIC_API_KEY
python scripts/run_narrative.py      # + live narrative generation (costs tokens)
```
