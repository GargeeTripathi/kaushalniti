"""FastAPI app. Thin: validation and routing only; the logic lives in service/resolver/data."""
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import service
from .data import NotFound, store

Scenario = Literal["LOW", "MEDIAN", "HIGH"]
HORIZON = dict(ge=1, le=60)

app = FastAPI(
    title="KaushalNiti API",
    version="1.0.0",
    description="Skill Gap Resolver for SIH PS 26246. Demo demand, costs, yields, capacities and surplus pools "
                "are SYNTHETIC / illustrative; see /api/data-status.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("KAUSHALNITI_CORS_ORIGINS", "http://localhost:5173").split(",")],
    allow_methods=["GET", "POST"], allow_headers=["*"],
)


class InterventionOverride(BaseModel):
    cost: float | None = Field(None, gt=0, le=1e7, description="Rupees per starter")
    yield_: float | None = Field(None, gt=0, le=1, alias="yield", description="Share of starters who become workers")
    lead: int | None = Field(None, ge=0, le=120, description="Lead time in months")
    capacity: float | None = Field(None, ge=0, le=1e7, description="Maximum starters")
    model_config = {"populate_by_name": True}


class Overrides(BaseModel):
    """Planner edits to the stated assumptions. Anything omitted keeps the dataset value."""
    interventions: dict[Literal["new_seats", "bridge", "neighbour", "apprenticeship"], InterventionOverride] = {}
    unmet_penalty: float | None = Field(None, gt=0, le=1e8)
    adjacency_threshold: float | None = Field(None, ge=0, le=1)
    mobility_decay_km: float | None = Field(None, gt=0, le=5000)
    bridge_cost_per_hour: float | None = Field(None, gt=0, le=1e5)
    bridge_hours_per_month: float | None = Field(None, gt=0, le=744)
    placement_months: int | None = Field(None, ge=0, le=24)


class Cell(BaseModel):
    district: str
    trade: str


class ResolveRequest(BaseModel):
    state: str | None = None
    district: str
    trade: str
    budget: float = Field(gt=0, le=1e12, description="Rupees available across all co-planned cells")
    horizon: int = Field(18, **HORIZON, description="Planning horizon in months")
    scenario: Scenario = "MEDIAN"
    include_cells: list[Cell] = Field([], max_length=20, description="Other shortages planned together: they share the budget and surplus pools")
    overrides: Overrides = Overrides()


def found(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except NotFound as e:
        raise HTTPException(404, str(e))


@app.get("/api/health")
def health():
    s = store()
    return {"status": "ok", "cells": len(s.cells()), "adjacency_edges": len(s.adjacency["edges"]), "mode": "offline demo dataset"}


@app.get("/api/meta")
def meta():
    """Selectors and default assumptions for the UI."""
    s = store()
    iv, params, _ = s.settings()
    demo = s.params["demo"]
    return {
        "states": sorted(set(s.state_of.values())),
        "districts": [{"state": r.state, "district": r.district} for r in s.districts.itertuples()],
        "trades": s.trades.to_dict("records"),
        "demo": demo,
        "assumptions": service.assumptions(iv, params, demo["budget"], demo["horizon"], "MEDIAN"),
    }


@app.get("/api/gap")
def gap(district: str | None = None, trade: str | None = None, state: str | None = None,
        horizon: int = Query(18, **HORIZON)):
    """Forecast gap. With district and trade: one cell with its history and forecast. Otherwise: every matching cell."""
    s = store()
    if district and trade:
        found(s.check, district, trade, state)
        sc, series = s.scenarios(district, trade, horizon), s.series(district, trade)
        return {**s.gap(district, trade, horizon),
                "history": [{"month": m, "openings": float(v)} for m, v in zip(series.month, series.openings)],
                "forecast_monthly": sc["monthly"], "band": sc["band"], "method": sc["method"],
                "status": "SYNTHETIC demand series; MODELLED forecast"}
    if state and state not in set(s.state_of.values()):
        raise HTTPException(404, f"unknown state '{state}'")
    cells = [c for c in s.cells(state) if (not district or c[0] == district) and (not trade or c[1] == trade)]
    if not cells:
        raise HTTPException(404, "no data for that selection")
    return {"horizon": horizon, "status": "SYNTHETIC demand series; MODELLED forecast",
            "cells": sorted((s.gap(d, t, horizon) for d, t in cells), key=lambda g: -g["shortage"]["MEDIAN"])}


@app.get("/api/scenarios")
def scenarios(district: str, trade: str, horizon: int = Query(18, **HORIZON)):
    """How LOW / MEDIAN / HIGH are built for one cell."""
    s = store()
    found(s.check, district, trade)
    sc = s.scenarios(district, trade, horizon)
    return {"district": district, "trade": trade, "horizon": horizon,
            "demand": {k: round(sc[k]) for k in ("LOW", "MEDIAN", "HIGH")},
            "band": sc["band"], "backtest_errors": sc["backtest_errors"], "method": sc["method"],
            "probabilities": s.params["scenario_probabilities"],
            "status": "MODELLED on a SYNTHETIC series; the band is not real-world forecast accuracy"}


@app.post("/api/resolve")
def resolve(req: ResolveRequest):
    """Run the Skill Gap Resolver for one shortage cell (optionally co-planned with others)."""
    s = store()
    found(s.check, req.district, req.trade, req.state)
    for c in req.include_cells:
        found(s.check, c.district, c.trade)
    try:
        return service.resolve(s, req.district, req.trade, req.budget, req.horizon, req.scenario,
                               [(c.district, c.trade) for c in req.include_cells],
                               req.overrides.model_dump(by_alias=True, exclude_none=True))
    except RuntimeError as e:  # the solver could not find a plan
        raise HTTPException(422, f"No plan could be computed: {e}")


@app.get("/api/adjacency/{trade}")
def adjacency(trade: str, district: str | None = None):
    """Source qualifications that could bridge into `trade`, with matched and unmatched standards."""
    s = store()
    if trade not in s.nqr_id:
        raise HTTPException(404, f"unknown trade '{trade}'")
    if district and district not in s.coords:
        raise HTTPException(404, f"unknown district '{district}'")
    threshold = s.params["adjacency_threshold"]
    target = int(s.nqr_id[trade])
    edges = []
    for e in s.adjacency["edges"]:
        if e["target_id"] != target:
            continue
        source_trade = s.trade_of.get(e["source_id"])
        surplus = s.pool.get((district, source_trade)) if district and source_trade else None
        eligible = e["score"] >= threshold
        edges.append({**e, "demo_trade": source_trade, "surplus": surplus, "eligible": eligible,
                      "used_by_optimiser": bool(eligible and surplus)})
    if not edges:
        raise HTTPException(404, f"no adjacency data for '{trade}'")
    a = s.adjacency
    return {"trade": trade, "target_id": target, "source_url": f"https://nqr.gov.in/qualifications/{target}",
            "threshold": threshold, "method": a["method"], "model": a["model"], "match_threshold": a["match_threshold"],
            "status": a["status"], "register_scraped_on": a["register_scraped_on"], "edges": edges}


@app.get("/api/data-status")
def data_status():
    """Provenance of every dataset: REAL / PUBLIC, SYNTHETIC, MODELLED or ESTIMATED."""
    return store().datasets


# Serve the built frontend from the same process when it exists (single-container deploy).
DIST = Path(os.environ.get("KAUSHALNITI_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
