# Data dictionary and provenance

Status labels used everywhere (UI badges, API, export):

| Label | Meaning |
|---|---|
| REAL / PUBLIC | Taken from a public official source |
| SYNTHETIC | Invented for the demonstration; not observed anywhere |
| MODELLED | Computed by a stated model from other inputs |
| ESTIMATED | Derived from real data by a stated heuristic; not expert-validated |

The machine-readable version of this page is `data/metadata/datasets.json`, served at `/api/data-status`.

## Files

### `data/processed/qualifications.json` · REAL / PUBLIC

480 qualifications from the [National Qualifications Register](https://nqr.gov.in) in four sectors: Electronics & HW (234), Automotive (119), Capital Goods & Manufacturing (105), Power (22). Produced by `scripts/scrape_nqr.py`; the scrape date is in the file.

| Field | Meaning |
|---|---|
| `nqr_id`, `source_url` | Register id and page |
| `title`, `nqr_code`, `version` | As published |
| `sector`, `occupation`, `nsqf_level`, `notional_hours` | As published |
| `awarding_body`, `qualification_type`, `applicability` | As published (`STT`, `LTT`, `For TOT`, ...) |
| `approved_on`, `valid_till` | As published |
| `standards[]` | `title`, `code`, `version`, `mandatory`, `hours`, `credits`, `level` |

Limits: a snapshot; NCO codes appear only in the qualification PDFs and are not captured; standard codes are inconsistently formatted and sometimes missing on the register.

### `data/processed/adjacency.json` · ESTIMATED

Built by `python -m kaushalniti.adjacency` from the file above. One edge per (source, target) with `score`, `bridge_hours`, `matched[]`, `unmatched[]`, levels and sectors. Stores up to 25 sources per demo trade with score ≥ 0.10.

### `data/metadata/adjacency_validation.csv`

51 reviewed pairs: model score, model eligibility, reviewer judgement, reason, reviewer. The reviewer column states that this is an AI-assisted desk review.

### `data/demo/` · SYNTHETIC unless stated

Regenerate with `python scripts/generate_demo_data.py` (fixed seeds; CI checks the committed files match).

| File | Columns | Notes |
|---|---|---|
| `districts.csv` | state, district, lat, lon | Names and approximate headquarters coordinates are real |
| `trades.csv` | trade, nqr_id, sector | Real register titles and ids |
| `demand_history.csv` | district, trade, month, openings | 60 months × 56 cells. Trend × 3-year cycle × noise |
| `training_capacity.csv` | district, trade, annual_seats, pipeline_yield | Gives existing pipeline supply |
| `surplus_pools.csv` | district, trade, surplus | Certified graduates not yet placed |
| `interventions.csv` | kind, cost_per_starter, yield, lead_time_months, capacity | Defaults per intervention |
| `capacities.csv` | district, trade, kind, capacity | Per-cell overrides of the default capacity |
| `params.json` | penalty, thresholds, bridge cost per hour, mobility decay, scenario probabilities, demo selection | Model constants |

The Pune / Electric Vehicle Service Technician series was shaped so the demo shortage is about 1,200 with a wide band. The app still computes the shortage, the band and the plan from the files.

## What is not fabricated

The project contains no invented government statistics, no district-to-district worker flows, no live NCS or SIDH feed, no official district-level trade demand and no validated bridge durations. Where one of these would be needed, a synthetic, modelled or estimated value is used and labelled.

## Public data that would replace synthetic inputs

| Dataset | Replaces | Access |
|---|---|---|
| [PMKVY district-wise enrolled, trained, certified, placed](https://www.data.gov.in/resource/district-wise-enrolled-trained-assessed-certified-placed-under-pmkvy-21-april-2022) | Pipeline yields | data.gov.in download form. Save as `data/raw/pmkvy_district.csv` (state, district, enrolled, trained, assessed, certified, placed) |
| [NAPS apprentices engaged by district](https://data.gov.in/resource/district-wise-apprentices-engaged-under-national-promotion-apprenticeship-scheme-naps-22nd) | Apprenticeship capacity | data.gov.in download form. Save as `data/raw/naps_district.csv` (financial_year, state, district, apprentices_engaged) |
| [PLFS unit-level data](https://microdata.gov.in) | Demand level calibration | Registration; district × occupation cells are thin |
| [Census 2011 table B-28](https://censusindia.gov.in/nada/index.php/catalog/13981) | Mobility decay length | Free download |
| DGT ITI seat data | New-seat capacity | Per-institute pages; no consolidated file found |

`data/raw/` is git-ignored. These loaders are not written yet; the columns above are the intended shape.

## Re-scraping the register

```bash
python scripts/scrape_nqr.py                    # default sectors 4, 7, 11, 35
python scripts/scrape_nqr.py --sectors 4 9      # NQR sector ids
pip install -r backend/requirements-build.txt
cd backend && python -m kaushalniti.adjacency   # rebuild the graph
python ../scripts/validate_adjacency.py
```

The scraper waits between requests and caches pages in `data/raw/nqr/`. The app never contacts the register.
