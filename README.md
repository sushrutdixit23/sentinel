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
      **Run live and verified** — all 7 flags across 5 companies narrated
      successfully. Two real bugs found and fixed from that live run:
      (1) Claude Sonnet 5's adaptive thinking silently consumed the entire
      token budget on one flag, leaving no visible text — fixed by passing
      `thinking={"type": "disabled"}` explicitly, since the reasoning step
      is already handled by this module's own two-turn structure; (2) a
      company with multiple flags (Apollo: a PAT swing AND an outsized
      exceptional item) was narrated as two disconnected calls that
      couldn't reference each other, and the exceptional-item metric had
      no peer comparison data at all — fixed by making
      `exceptional_item_pct_of_pbt` a proper engine-computed ratio
      (`config/sectors/tyre.yaml`) and bundling a company's flags into one
      narrative pass via `group_flags_by_company()`.
- [ ] Dashboard (Streamlit) — reframed per discussion: not just a display
      layer, but the review/approval step before a narrative counts as
      final, following the same supervised pattern as [[zyntask-engage]]'s
      magic review link
- [ ] Real (non-manual) filing ingestion — currently 9 companies'
      quarters/years are hand-extracted from uploaded PDFs; a sellable
      version needs a user to upload/point at their own filings and get
      them parsed automatically. This is the next concrete build target.

Run `python scripts/run_anomaly.py` for the full pipeline through anomaly
detection (no API key needed). Run `python scripts/run_narrative.py` for
the narrative layer on top — now makes 2 calls per COMPANY (not per flag),
so 7 flags across 5 companies costs 10 calls, not 14.

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
