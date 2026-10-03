"""Optimiser tests on a hand-checkable problem (the README worked example)."""
import pytest

from kaushalniti.resolver import (Pathway, Problem, binding_constraints, classify, cost, evaluate, feasible,
                                  resolve, round_plan, seats_only, solve, supplied, timeline, unmet)

CELL = ("Pune", "EV")
PROBS = {"LOW": 0.25, "MEDIAN": 0.5, "HIGH": 0.25}


def make(budget=6e7, horizon=18, gaps=(600, 1200, 1600), extra_cell=False):
    cells = [CELL]
    paths = [
        Pathway("new_seats", "new_seats", CELL, 60000, 0.32, 13, 800),
        Pathway("bridge:MMV", "bridge", CELL, 15000, 0.75, 4, 400, pool=("Pune", "MMV")),
        Pathway("neighbour:Satara", "neighbour", CELL, 10000, 0.60, 2, 250, pool=("Satara", "EV")),
        Pathway("apprenticeship", "apprenticeship", CELL, 18000, 0.80, 3, 250),
    ]
    caps = {("new_seats", CELL): 800, ("bridge", CELL): 400, ("neighbour", CELL): 250, ("apprenticeship", CELL): 250}
    demand = {CELL: dict(zip(("LOW", "MEDIAN", "HIGH"), gaps))}
    baseline = {CELL: 0}
    if extra_cell:  # a second shortage that wants the same Motor Vehicle Mechanic surplus
        c2 = ("Pune", "Charger")
        cells.append(c2)
        paths.append(Pathway("bridge:MMV", "bridge", c2, 15000, 0.75, 4, 400, pool=("Pune", "MMV")))
        caps[("bridge", c2)] = 400
        demand[c2] = {"LOW": 200, "MEDIAN": 200, "HIGH": 200}
        baseline[c2] = 0
    return Problem(cells, demand, baseline, paths, caps, {("Pune", "MMV"): 400, ("Satara", "EV"): 250},
                   budget, horizon, penalty=300000)


def plan(problem, scenario="MEDIAN"):
    x, _ = solve(problem, {scenario: 1.0})
    return round_plan(problem, x)


def test_median_uses_short_cycle_first_then_seats():
    p = make()
    seats, bridge, neighbour, appr = plan(p)
    assert (bridge, neighbour, appr) == (400, 250, 250)
    assert seats == 783  # (6 crore - 1.3 crore) / 60,000, rounded down
    assert supplied(p, plan(p), CELL) == pytest.approx(900.56)


def test_budget_constraint():
    for budget in (1e6, 1e7, 6e7):
        p = make(budget=budget)
        assert cost(p, plan(p, "HIGH")) <= budget


def test_capacity_constraint():
    p = make(budget=1e9)
    x = plan(p, "HIGH")
    for xi, path in zip(x, p.pathways):
        assert xi <= path.cap


def test_shared_surplus_pool_is_not_double_counted():
    p = make(extra_cell=True)
    x = plan(p, "HIGH")
    used = sum(xi for xi, path in zip(x, p.pathways) if path.pool == ("Pune", "MMV"))
    assert used == 400  # fully used, never more than exists


def test_cells_compete_for_the_shared_pool():
    # the second cell can only be supplied by bridging, so it gets first call on the pool
    # and the first cell makes up the difference with new seats
    p = make(extra_cell=True)
    x = plan(p, "LOW")
    assert x[4] >= 266 and x[1] + x[4] <= 400
    assert x[0] > 0
    assert all(unmet(p, x, c, "LOW") < 1 for c in p.cells)


def test_deadline_excludes_slow_pathways():
    p = make(horizon=12)  # new seats need 13 months
    assert plan(p, "HIGH")[0] == 0
    assert any(r["constraint"] == "deadline" for r in binding_constraints(p, plan(p, "HIGH"), CELL, "HIGH"))


def test_low_demand_needs_no_new_seats():
    p = make()
    x = plan(p, "LOW")
    assert x[0] == 0
    assert unmet(p, x, CELL, "LOW") < 1


def test_seats_only_baseline():
    p = make()
    b = seats_only(p, CELL, "MEDIAN")
    assert b["seats_required"] == 3750
    assert b["cost_required"] == 3750 * 60000
    assert b["seats_feasible"] == 800 and b["binding"] == ["capacity"]
    assert b["workers_delivered"] == pytest.approx(256)
    assert b["residual_gap"] == pytest.approx(944)
    assert b["timeline"][12] == 0 and b["timeline"][13] == pytest.approx(256)


def test_seats_only_budget_bound():
    b = seats_only(make(budget=1.2e7), CELL, "MEDIAN")
    assert b["seats_feasible"] == 200 and b["binding"] == ["budget"]


def test_timeline_is_cumulative_and_steps_at_lead_times():
    p = make()
    t = timeline(p, plan(p), CELL)
    assert len(t) == 19 and t == sorted(t)
    assert t[1] == 0 and t[2] == 150 and t[3] == 350 and t[4] == 650


def test_regret_and_classification():
    p = make()
    r = resolve(p, PROBS)
    for s in ("LOW", "MEDIAN", "HIGH"):
        assert r["regret"][s][s] < p.penalty  # own-scenario regret is under one worker of rounding loss
    assert r["regret"]["MEDIAN"]["LOW"] > 4e7  # seats bought for nothing if demand is low
    assert r["regret"]["LOW"]["MEDIAN"] > 0
    classes = {path.id: c["class"] for path, c in zip(p.pathways, r["classes"])}
    assert classes == {"new_seats": "CONTINGENT", "bridge:MMV": "NO_REGRET",
                       "neighbour:Satara": "NO_REGRET", "apprenticeship": "MIXED"}


def test_classify_labels():
    out = classify({"LOW": [0, 5, 5, 0], "MEDIAN": [3, 5, 8, 0], "HIGH": [3, 5, 9, 0]})
    assert [c["class"] for c in out] == ["CONTINGENT", "NO_REGRET", "MIXED", "NOT_USED"]
    assert out[2]["no_regret_starters"] == 5 and out[2]["contingent_starters"] == 4


def test_binding_constraints_explain_residual():
    p = make()
    reasons = {r["constraint"] for r in binding_constraints(p, plan(p, "HIGH"), CELL, "HIGH")}
    assert {"budget", "capacity", "surplus"} <= reasons
    assert binding_constraints(p, plan(p, "LOW"), CELL, "LOW") == []


def test_evaluate_adds_penalty_for_unmet():
    p = make()
    x = plan(p, "LOW")
    assert evaluate(p, x, "HIGH") == pytest.approx(cost(p, x) + 300000 * unmet(p, x, CELL, "HIGH"))


def test_zero_gap_does_nothing():
    p = make(gaps=(0, 0, 0))
    assert sum(plan(p)) == 0
    assert seats_only(p, CELL, "MEDIAN")["seats_required"] == 0


def test_rounding_gives_whole_feasible_starters():
    for scenario in ("LOW", "MEDIAN", "HIGH"):
        p = make(extra_cell=True)
        x = plan(p, scenario)
        assert all(v == int(v) for v in x) and feasible(p, x)


def test_rounding_up_closes_the_gap_when_it_is_affordable():
    p = make()
    x = plan(p, "LOW")  # apprenticeship is 187.5 in the LP; 188 closes the gap, 187 would not
    assert x[3] == 188 and unmet(p, x, CELL, "LOW") == 0


def test_feasible_rejects_overspend_and_pool_overdraw():
    p = make(budget=1e6)
    assert not feasible(p, [100, 0, 0, 0])   # 60 lakh of seats on a 10 lakh budget
    assert not feasible(make(), [0, 401, 0, 0])  # more bridge starters than the pool holds
