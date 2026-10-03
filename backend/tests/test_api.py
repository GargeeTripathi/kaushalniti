"""API and end-to-end tests on the committed demo dataset."""
import pytest
from fastapi.testclient import TestClient

from kaushalniti.api import app
from kaushalniti.data import store

client = TestClient(app)
EV = "Electric Vehicle Service Technician"
HMV = "Service Technician (Heavy Motor Vehicle)"
CAR = "Four Wheeler Service Technician"
DEMO = {"state": "Maharashtra", "district": "Pune", "trade": EV, "budget": 6e7, "horizon": 18}


def resolve(**changes):
    return client.post("/api/resolve", json={**DEMO, **changes})


def card(result, kind):
    return next(c for c in result["plan"]["interventions"] if c["kind"] == kind)


def test_health():
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["cells"] == 56 and body["adjacency_edges"] > 0


def test_meta_lists_selectors_and_assumptions():
    body = client.get("/api/meta").json()
    assert body["demo"]["district"] == "Pune" and len(body["trades"]) == 8
    assert all(a["status"] for a in body["assumptions"])


def test_gap_for_one_cell():
    body = client.get("/api/gap", params={"district": "Pune", "trade": EV}).json()
    assert body["shortage"]["LOW"] <= body["shortage"]["MEDIAN"] <= body["shortage"]["HIGH"]
    assert body["shortage"]["MEDIAN"] == body["demand"]["MEDIAN"] - body["baseline_supply"]
    assert len(body["history"]) == 60 and len(body["forecast_monthly"]) == 18
    assert "SYNTHETIC" in body["status"]


def test_gap_for_a_district():
    cells = client.get("/api/gap", params={"state": "Maharashtra", "district": "Pune"}).json()["cells"]
    assert len(cells) == 8 and cells[0]["trade"] == EV


def test_scenarios():
    body = client.get("/api/scenarios", params={"district": "Pune", "trade": EV}).json()
    assert body["demand"]["LOW"] < body["demand"]["MEDIAN"] < body["demand"]["HIGH"]
    assert sum(body["probabilities"].values()) == 1 and len(body["backtest_errors"]) >= 5


def test_data_status_labels_everything():
    body = client.get("/api/data-status").json()
    assert "synthetic" in body["notice"].lower()
    assert all(d["status"] for d in body["included"])


def test_adjacency():
    body = client.get(f"/api/adjacency/{EV}", params={"district": "Pune"}).json()
    by_trade = {e["demo_trade"]: e for e in body["edges"] if e["demo_trade"]}
    car = by_trade[CAR]
    assert car["used_by_optimiser"] and car["matched"] and car["bridge_hours"] > 0
    assert any(u["title"].startswith("High voltage") for u in car["unmatched"])
    assert not by_trade["Four Wheeler Service Assistant"]["eligible"]  # below the threshold


@pytest.mark.parametrize("payload,code", [
    ({"budget": 0}, 422), ({"budget": -5}, 422), ({"budget": "lots"}, 422),
    ({"scenario": "MAYBE"}, 422), ({"horizon": 0}, 422), ({"horizon": 500}, 422),
    ({"district": "Atlantis"}, 404), ({"trade": "Wizard"}, 404), ({"state": "Kerala"}, 404),
    ({"overrides": {"interventions": {"bridge": {"yield": 1.5}}}}, 422),
    ({"overrides": {"interventions": {"teleport": {"cost": 1}}}}, 422),
    ({"include_cells": [{"district": "Pune", "trade": "Wizard"}]}, 404),
])
def test_invalid_requests_are_rejected(payload, code):
    r = resolve(**payload)
    assert r.status_code == code and r.json()["detail"]


def test_missing_fields_are_rejected():
    assert client.post("/api/resolve", json={"budget": 1e7}).status_code == 422
    assert client.get("/api/gap", params={"district": "Atlantis", "trade": EV}).status_code == 404
    assert client.get("/api/adjacency/Wizard").status_code == 404


def test_end_to_end_demo():
    """Pune, EV Service Technician, 6 crore, 18 months. Checks constraints, not a fixed answer."""
    plans = {s: resolve(scenario=s).json() for s in ("LOW", "MEDIAN", "HIGH")}
    r = plans["MEDIAN"]
    gap = r["shortage"]["MEDIAN"]
    assert gap > 0 and r["plan"]["total_cost"] <= 6e7  # budget respected

    cards = {c["kind"]: c for c in r["plan"]["interventions"]}
    assert set(cards) == {"new_seats", "bridge", "neighbour", "apprenticeship"}
    assert all(c["starters"] <= c["capacity"] for c in cards.values())  # capacity respected

    pools = store().pool
    for p in r["plan"]["pathways"]:
        d = p["detail"]
        if p["kind"] == "bridge":  # shared surplus respected
            assert p["starters"] <= pools[("Pune", d["source_trade"])]
        if p["kind"] == "neighbour":
            assert p["starters"] <= d["reach"] * pools[(d["source_district"], EV)] + 1
        assert p["within_horizon"] or p["starters"] == 0  # deadline respected

    # workers-by-month and the seats-only comparison
    assert len(r["plan"]["timeline"]) == 19 and r["plan"]["timeline"] == sorted(r["plan"]["timeline"])
    assert r["plan"]["timeline"][-1] == pytest.approx(r["plan"]["workers_delivered"], abs=0.2)
    seats = r["seats_only"]
    assert seats["seats_required"] * 0.32 >= gap and seats["seats_feasible"] <= seats["capacity"]
    assert r["plan"]["workers_delivered"] > seats["workers_delivered"]
    assert next(m for m, v in enumerate(r["plan"]["timeline"]) if v > 0) < seats["lead_time_months"]

    # scenario analysis and no-regret classification
    assert plans["LOW"]["plan"]["workers_delivered"] <= r["plan"]["workers_delivered"] <= plans["HIGH"]["plan"]["workers_delivered"] + 0.1
    assert plans["LOW"]["plan"]["residual_gap"] <= r["plan"]["residual_gap"] <= plans["HIGH"]["plan"]["residual_gap"]
    assert cards["new_seats"]["class"] == "CONTINGENT" and cards["bridge"]["class"] == "NO_REGRET"
    assert card(plans["LOW"], "new_seats")["starters"] == 0
    assert "Defer" in r["actions"]["recommendation"] and "Launch now" in r["actions"]["recommendation"]
    assert r["regret"]["MEDIAN"]["LOW"] > r["regret"]["LOW"]["LOW"]
    assert r["plan"]["binding_constraints"] and any("remains" in line for line in r["explanation"])


def test_resolver_is_deterministic():
    assert resolve().json() == resolve().json()


def test_overrides_change_the_plan():
    base = resolve().json()
    cheap_seats = resolve(overrides={"interventions": {"new_seats": {"cost": 20000, "capacity": 5000}}}).json()
    assert cheap_seats["plan"]["workers_delivered"] > base["plan"]["workers_delivered"]
    strict = resolve(overrides={"adjacency_threshold": 0.9}).json()
    assert card(strict, "bridge")["starters"] == 0


def test_short_horizon_excludes_new_seats_and_says_why():
    r = resolve(horizon=12, scenario="HIGH").json()
    assert card(r, "new_seats")["starters"] == 0
    assert any(b["constraint"] == "deadline" for b in r["plan"]["binding_constraints"])


def test_co_planned_cells_share_budget_and_pool():
    r = resolve(include_cells=[{"district": "Pune", "trade": HMV}], scenario="HIGH").json()
    assert r["plan"]["total_cost"] <= 6e7 and r["other_cells"][0]["trade"] == HMV
    shared = [p for p in r["plan"]["pathways"] if p["id"] == f"bridge:{CAR}"]
    assert {p["trade"] for p in shared} == {EV, HMV}  # both shortages can draw on the same pool
    assert sum(p["starters"] for p in shared) <= store().pool[("Pune", CAR)]


def test_cell_with_no_shortage_plans_nothing():
    r = resolve(trade=CAR).json()
    assert r["shortage"]["HIGH"] == 0 and r["plan"]["total_cost"] == 0
    assert "No intervention is needed" in r["actions"]["recommendation"]
