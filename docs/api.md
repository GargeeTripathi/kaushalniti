# API reference

Base URL `http://localhost:8000`. JSON in, JSON out. The OpenAPI schema and an interactive console are at `/docs`.

Errors use FastAPI's shape: `{"detail": "..."}` with status 404 for an unknown state, district or trade, and 422 for an invalid value (`detail` is then a list of field errors).

## GET /api/health

```json
{"status": "ok", "cells": 56, "adjacency_edges": 93, "mode": "offline demo dataset"}
```

## GET /api/meta

States, districts, trades, the demo selection and the default assumptions with their provenance. Used by the UI to fill its selectors.

## GET /api/gap

| Query | Required | Meaning |
|---|---|---|
| `district`, `trade` | both, for one cell | One cell with history and monthly forecast |
| `state`, `district`, `trade` | any | Without the pair above: every matching cell, largest shortage first |
| `horizon` | no (18) | Months, 1 to 60 |

`GET /api/gap?district=Pune&trade=Electric Vehicle Service Technician`

```json
{
  "district": "Pune", "trade": "Electric Vehicle Service Technician", "state": "Maharashtra", "horizon": 18,
  "demand": {"LOW": 917, "MEDIAN": 1543, "HIGH": 1928},
  "baseline_supply": 288,
  "shortage": {"LOW": 629, "MEDIAN": 1255, "HIGH": 1640},
  "surplus": 0,
  "history": [{"month": "2021-10", "openings": 69.0}, "..."],
  "forecast_monthly": [66.3, "..."],
  "band": [-0.406, 0.249],
  "method": "damped Holt forecast; band = 10th/90th percentile of 19 rolling-origin back-test errors on this series",
  "status": "SYNTHETIC demand series; MODELLED forecast"
}
```

## GET /api/scenarios

`?district=&trade=&horizon=` → the three demand levels, the band, the back-test errors behind it, the scenario probabilities and the method.

## POST /api/resolve

Request:

| Field | Type | Notes |
|---|---|---|
| `district`, `trade` | string | Required |
| `state` | string | Optional; checked against the district if given |
| `budget` | number > 0 | Rupees, shared by all co-planned cells |
| `horizon` | integer 1–60 | Months; default 18 |
| `scenario` | `LOW` \| `MEDIAN` \| `HIGH` | Which plan to return in detail; default `MEDIAN` |
| `include_cells` | list of `{district, trade}` | Other shortages planned together |
| `overrides` | object | Planner edits to assumptions (below) |

`overrides`:

```json
{
  "interventions": {"new_seats": {"cost": 50000, "yield": 0.35, "lead": 12, "capacity": 1000}},
  "unmet_penalty": 300000,
  "adjacency_threshold": 0.6,
  "max_level_gap": 1,
  "mobility_decay_km": 150,
  "bridge_cost_per_hour": 50,
  "bridge_hours_per_month": 120,
  "placement_months": 1
}
```

Example:

```bash
curl -X POST localhost:8000/api/resolve -H "Content-Type: application/json" -d '{
  "state": "Maharashtra", "district": "Pune", "trade": "Electric Vehicle Service Technician",
  "budget": 60000000, "horizon": 18, "scenario": "MEDIAN"
}'
```

Response (abridged):

```json
{
  "cell": {"state": "Maharashtra", "district": "Pune", "trade": "Electric Vehicle Service Technician"},
  "scenario": "MEDIAN", "horizon": 18, "budget": 60000000.0,
  "forecast": {"demand": {"LOW": 917, "MEDIAN": 1543, "HIGH": 1928}, "method": "...", "band": [-0.406, 0.249]},
  "baseline_supply": 288,
  "shortage": {"LOW": 629, "MEDIAN": 1255, "HIGH": 1640},
  "seats_only": {
    "seats_required": 3923, "cost_required": 235380000.0, "capacity": 800, "lead_time_months": 13,
    "seats_feasible": 800, "cost": 48000000.0, "workers_delivered": 256.0, "residual_gap": 999.3,
    "binding": ["capacity"], "timeline": [0.0, "...", 256.0]
  },
  "plan": {
    "interventions": [
      {"kind": "new_seats", "label": "New training seats", "starters": 780, "workers_delivered": 249.6,
       "cost": 46800000, "lead_time_months": 13, "capacity": 800, "class": "CONTINGENT",
       "no_regret_starters": 0, "contingent_starters": 780, "status": "SYNTHETIC", "available": true},
      "... bridge, neighbour, apprenticeship"
    ],
    "pathways": ["one row per concrete pathway, with detail (source trade or district, score, hours, distance, reach)"],
    "total_cost": 59960000, "cost_this_cell": 59960000,
    "workers_delivered": 899.6, "residual_gap": 355.7,
    "timeline": [0.0, 0.0, 150.0, 350.0, 650.0, "...", 899.6],
    "binding_constraints": [{"constraint": "budget", "detail": "the budget is fully committed"}, "..."]
  },
  "scenarios": {"LOW": {"total_cost": 12692000, "workers_delivered": 629.2, "starters_by_kind": {"new_seats": 0, "...": 0}}, "...": {}},
  "regret": {"LOW": {"LOW": 12373, "MEDIAN": 33876000, "HIGH": 33876000}, "MEDIAN": {"LOW": 47280373, "MEDIAN": 24000, "HIGH": 24000}, "...": {}},
  "actions": {"launch_now": ["..."], "defer": ["..."], "recommendation": "Launch now: ... Defer until the next demand update: ..."},
  "explanation": ["..."],
  "other_cells": [],
  "skipped_pathways": [{"kind": "bridge", "source_trade": "Four Wheeler Service Assistant", "reason": "adjacency 50% is below the 60% threshold"}],
  "assumptions": [{"key": "interventions.bridge.yield", "label": "...", "value": 0.75, "unit": "share", "status": "SYNTHETIC", "source": "SIH demonstration dataset", "editable": true}],
  "data_status": "..."
}
```

`class` is one of `NO_REGRET`, `CONTINGENT`, `MIXED`, `NOT_USED`. Regret keys are the plan chosen (`LOW`, `MEDIAN`, `HIGH`, `EXPECTED`), then the scenario that happens.

Error examples:

```
budget: 0                      → 422  budget: Input should be greater than 0
scenario: "MAYBE"              → 422  scenario: Input should be 'LOW', 'MEDIAN' or 'HIGH'
district: "Atlantis"           → 404  unknown district 'Atlantis'
trade: "Wizard"                → 404  unknown trade 'Wizard'
```

A shortage that cannot be fully met is not an error: the plan returns `residual_gap` with `binding_constraints` saying why.

## GET /api/adjacency/{trade}

`?district=` adds the surplus available there. Returns the method, thresholds, scrape date and one edge per source qualification:

```json
{
  "source": "Four Wheeler Service Technician", "source_id": 12211, "score": 0.667, "bridge_hours": 308,
  "target_technical_hours": 540.0,
  "matched": [{"code": "ASC/N1451", "title": "Carry out routine service or minor repairs on 2 wheeler electric vehicle and assist in diagnosis",
               "hours": 90.0, "source_code": "ASC/N1403", "source_title": "Carry out routine service and minor repairs", "similarity": 0.639}],
  "unmatched": [{"code": "ASC/N9846", "title": "High voltage and fire safety practices", "hours": 180.0, "best_similarity": 0.211}],
  "demo_trade": "Four Wheeler Service Technician", "surplus": 400.0,
  "eligible": true, "not_eligible_because": [], "used_by_optimiser": true, "status": "ESTIMATED"
}
```

## GET /api/data-status

The contents of `data/metadata/datasets.json`: every dataset with its status, source and limits, and the public datasets that are not included.
