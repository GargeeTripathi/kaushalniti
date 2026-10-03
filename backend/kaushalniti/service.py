"""Turns resolver output into the structured plan the API returns.

Every number and every sentence here is read from the solved plan and its inputs.
No language model is involved: explanations are templates over optimiser output.
"""
from . import resolver
from .resolver import KINDS, SCENARIOS

LABELS = {"new_seats": "New training seats", "bridge": "Bridge course",
          "neighbour": "Neighbouring-district supply", "apprenticeship": "Apprenticeship"}
STATUS = {  # provenance of each intervention's parameters in the demo dataset
    "new_seats": "SYNTHETIC", "apprenticeship": "SYNTHETIC",
    "bridge": "SYNTHETIC yield and surplus; ESTIMATED hours from REAL qualification data",
    "neighbour": "SYNTHETIC surplus; MODELLED reach (distance decay)",
}


def rupees(v):
    return f"₹{v / 1e7:.2f} crore" if v >= 1e7 else f"₹{v / 1e5:.2f} lakh" if v >= 1e5 else f"₹{v:,.0f}"


def pathway_rows(problem, x, classes):
    rows = []
    for p, xi, cls in zip(problem.pathways, x, classes):
        rows.append({
            "id": p.id, "kind": p.kind, "label": LABELS[p.kind],
            "district": p.cell[0], "trade": p.cell[1],
            "starters": int(xi), "workers_delivered": round(p.yield_ * xi, 1), "cost": round(p.cost * xi),
            "cost_per_starter": round(p.cost), "yield": p.yield_, "lead_time_months": p.lead,
            "capacity": round(p.cap), "cost_per_worker": round(p.cost / p.yield_),
            "within_horizon": problem.in_time(p),
            "class": cls["class"], "no_regret_starters": int(cls["no_regret_starters"]),
            "contingent_starters": int(cls["contingent_starters"]),
            "starters_by_scenario": {s: int(v) for s, v in cls["by_scenario"].items()},
            "status": STATUS[p.kind], "detail": p.detail,
        })
    return rows


def by_kind(rows, problem, cell):
    """One card per intervention type for the selected cell."""
    cards = []
    for kind in KINDS:
        mine = [r for r in rows if r["kind"] == kind and (r["district"], r["trade"]) == cell]
        used = [r for r in mine if r["starters"] > 0]
        lo = sum(r["no_regret_starters"] for r in mine)
        hi = sum(max(r["starters_by_scenario"].values()) for r in mine)
        cards.append({
            "kind": kind, "label": LABELS[kind],
            "starters": sum(r["starters"] for r in mine),
            "workers_delivered": round(sum(r["workers_delivered"] for r in mine), 1),
            "cost": sum(r["cost"] for r in mine),
            "lead_time_months": min((r["lead_time_months"] for r in used or mine), default=None),
            "capacity": round(problem.kind_caps[(kind, cell)]),
            "class": "NOT_USED" if hi == 0 else "CONTINGENT" if lo == 0 else "NO_REGRET" if lo == hi else "MIXED",
            "no_regret_starters": lo, "contingent_starters": hi - lo,
            "status": STATUS[kind], "available": bool(mine),
        })
    return cards


def scenario_summary(problem, x, cell):
    return {
        "total_cost": round(resolver.cost(problem, x)),
        "workers_delivered": round(resolver.supplied(problem, x, cell), 1),
        "starters_by_kind": {k: int(sum(xi for p, xi in zip(problem.pathways, x) if p.kind == k and p.cell == cell))
                             for k in KINDS},
    }


def actions(cards):
    """Forecast uncertainty turned into a planning distinction: commit now vs defer."""
    now = [c for c in cards if c["no_regret_starters"] > 0]
    later = [c for c in cards if c["contingent_starters"] > 0]
    parts = []
    if now:
        parts.append("Launch now: " + ", ".join(f"{c['label'].lower()} ({c['no_regret_starters']:,} starters)" for c in now)
                     + ". These are needed in every demand scenario.")
    if later:
        parts.append("Defer until the next demand update: " + ", ".join(
            f"{c['label'].lower()} (up to {c['contingent_starters']:,} more starters)" for c in later)
            + ". These are needed only if demand turns out higher than the LOW scenario.")
    if not now and not later:
        parts.append("No intervention is needed: the existing pipeline covers demand in every scenario.")
    return {"launch_now": [{"kind": c["kind"], "label": c["label"], "starters": c["no_regret_starters"]} for c in now],
            "defer": [{"kind": c["kind"], "label": c["label"], "starters": c["contingent_starters"]} for c in later],
            "recommendation": " ".join(parts)}


def explain(problem, rows, cell, scenario, shortage, seats, plan_workers, plan_cost, binding, skipped):
    out = []
    if shortage <= 0:
        return [f"No shortage is forecast for {cell[1]} in {cell[0]} under the {scenario} scenario, so no intervention is planned."]
    out.append(f"Under the {scenario} scenario the plan supplies {plan_workers:,.0f} of the {shortage:,.0f} workers needed "
               f"for {rupees(plan_cost)}. Seats alone would supply {seats['workers_delivered']:,.0f} for {rupees(seats['cost'])}, "
               f"with the first workers in month {seats['lead_time_months']}.")
    mine = [r for r in rows if (r["district"], r["trade"]) == cell]
    used = sorted((r for r in mine if r["starters"] > 0), key=lambda r: r["lead_time_months"])
    near = [r for r in used if r["kind"] == "neighbour"]
    if near:  # one sentence for all neighbouring districts
        places = ", ".join(f"{r['detail']['source_district']} ({r['starters']:,} of a surplus of {r['detail']['pool']:,.0f}, "
                           f"{r['detail']['distance_km']} km)" for r in sorted(near, key=lambda r: -r["starters"]))
        out.append(f"Neighbouring-district supply: {sum(r['starters'] for r in near):,} starters deliver about "
                   f"{sum(r['workers_delivered'] for r in near):,.0f} workers in month {near[0]['lead_time_months']} at "
                   f"{rupees(near[0]['cost_per_worker'])} per worker, drawn from {places}. Reach falls with distance; "
                   f"this is a model, not observed movement.")
    for r in (r for r in used if r["kind"] != "neighbour"):
        d = r["detail"]
        head = (f"{r['label']}: {r['starters']:,} starters deliver about {r['workers_delivered']:,.0f} workers in month "
                f"{r['lead_time_months']} at {rupees(r['cost_per_worker'])} per worker.")
        if r["kind"] == "bridge":
            hours = f"about {d['bridge_hours']:,.0f} bridge hours remain" if d["bridge_hours"] else "bridge hours could not be estimated"
            head += (f" Source trade {d['source_trade']}: matching standards cover {d['score']:.0%} of the target's technical hours, "
                     f"{hours}, and {d['pool']:,.0f} surplus graduates are available (an estimate, not a validated course length).")
        out.append(head)
    seat_row = next((r for r in mine if r["kind"] == "new_seats"), None)
    if seat_row and seat_row["starters"] == 0:
        why = ("they cannot deliver within the horizon" if not seat_row["within_horizon"]
               else "cheaper and faster pathways already cover this scenario's shortage" if resolver_gap_closed(problem, rows, cell, shortage)
               else "the budget is spent on pathways that deliver more workers per rupee")
        out.append(f"New training seats are not used in this scenario because {why}.")
    for s in skipped:
        if tuple(s["cell"]) == cell:
            out.append(f"Bridge from {s['source_trade']} was not considered: {s['reason']}.")
    residual = max(0.0, shortage - plan_workers)
    if residual >= 1:
        out.append(f"A shortage of about {residual:,.0f} workers remains within the {problem.horizon}-month horizon because: "
                   + "; ".join(b["detail"] for b in binding) + ".")
    return out


def resolver_gap_closed(problem, rows, cell, shortage):
    return sum(r["workers_delivered"] for r in rows if (r["district"], r["trade"]) == cell) >= shortage - 1


def assumptions(iv, params, budget, horizon, scenario):
    """Everything the plan depends on, each with its provenance, for the assumptions panel."""
    rows = [
        {"key": "budget", "label": "Budget", "value": budget, "unit": "INR", "status": "PLANNER INPUT", "source": "request"},
        {"key": "horizon", "label": "Planning horizon", "value": horizon, "unit": "months", "status": "PLANNER INPUT", "source": "request"},
        {"key": "scenario", "label": "Demand scenario", "value": scenario, "unit": "", "status": "MODELLED", "source": "forecast back-test band on synthetic demand"},
    ]
    units = {"cost": ("Cost per starter", "INR"), "yield": ("Yield (starters who become workers)", "share"),
             "lead": ("Lead time", "months"), "capacity": ("Capacity", "starters")}
    for kind in KINDS:
        for f, (label, unit) in units.items():
            note = ""
            if kind == "bridge" and f in ("cost", "lead"):
                note = " (fallback: used only when bridge hours cannot be estimated)"
            rows.append({"key": f"interventions.{kind}.{f}", "label": f"{LABELS[kind]}: {label}{note}", "value": iv[kind][f],
                         "unit": unit, "status": "SYNTHETIC", "source": "SIH demonstration dataset", "editable": True})
    model = [
        ("unmet_penalty", "Penalty per unmet worker", "INR", "SYNTHETIC"),
        ("adjacency_threshold", "Adjacency threshold for bridge eligibility", "share", "MODELLED"),
        ("max_level_gap", "Largest NSQF level gap a bridge may span", "levels", "MODELLED"),
        ("mobility_decay_km", "Mobility distance-decay length", "km", "MODELLED"),
        ("bridge_cost_per_hour", "Bridge course cost per trainee-hour", "INR", "SYNTHETIC"),
        ("bridge_hours_per_month", "Bridge course hours delivered per month", "hours", "SYNTHETIC"),
        ("placement_months", "Months from course end to placement", "months", "SYNTHETIC"),
    ]
    for key, label, unit, status in model:
        rows.append({"key": key, "label": label, "value": params[key], "unit": unit, "status": status,
                     "source": "SIH demonstration dataset", "editable": True})
    for s, pr in params["scenario_probabilities"].items():
        rows.append({"key": f"scenario_probabilities.{s}", "label": f"Probability of {s} scenario", "value": pr,
                     "unit": "share", "status": "SYNTHETIC", "source": "SIH demonstration dataset"})
    return rows


def resolve(store, district, trade, budget, horizon, scenario, include_cells=(), overrides=None):
    cell = (district, trade)
    cells = [cell] + [tuple(c) for c in include_cells if tuple(c) != cell]
    problem, iv, params, skipped = store.problem(cells, budget, horizon, overrides)
    result = resolver.resolve(problem, params["scenario_probabilities"])
    x = result["plans"][scenario]
    rows = pathway_rows(problem, x, result["classes"])
    cards = by_kind(rows, problem, cell)
    seats = resolver.seats_only(problem, cell, scenario)
    shortage = problem.gap(cell, scenario)
    workers = resolver.supplied(problem, x, cell)
    plan_cost = resolver.cost(problem, x)
    binding = resolver.binding_constraints(problem, x, cell, scenario)
    sc = store.scenarios(district, trade, horizon)
    return {
        "cell": {"state": store.state_of[district], "district": district, "trade": trade},
        "scenario": scenario, "horizon": horizon, "budget": budget,
        "forecast": {"demand": {s: round(sc[s]) for s in SCENARIOS}, "method": sc["method"], "band": sc["band"]},
        "baseline_supply": round(problem.baseline[cell]),
        "shortage": {s: round(problem.gap(cell, s)) for s in SCENARIOS},
        "seats_only": {**seats, "workers_delivered": round(seats["workers_delivered"], 1),
                       "residual_gap": round(seats["residual_gap"], 1)},
        "plan": {
            "interventions": cards,
            "pathways": rows,
            "total_cost": round(plan_cost),  # all co-planned cells
            "cost_this_cell": sum(c["cost"] for c in cards),
            "workers_delivered": round(workers, 1),
            "residual_gap": round(max(0.0, shortage - workers), 1),
            "timeline": resolver.timeline(problem, x, cell),
            "binding_constraints": binding,
        },
        "scenarios": {s: scenario_summary(problem, result["plans"][s], cell) for s in SCENARIOS},
        "regret": {name: {s: round(v) for s, v in r.items()} for name, r in result["regret"].items()},
        "actions": actions(cards),
        "explanation": explain(problem, rows, cell, scenario, shortage, seats, workers,
                               sum(c["cost"] for c in cards), binding, skipped),
        "other_cells": [{"district": c[0], "trade": c[1], "shortage": round(problem.gap(c, scenario)),
                         "workers_delivered": round(resolver.supplied(problem, x, c), 1),
                         "residual_gap": round(resolver.unmet(problem, x, c, scenario), 1)} for c in cells[1:]],
        "skipped_pathways": skipped,
        "assumptions": assumptions(iv, params, budget, horizon, scenario),
        "data_status": "Demand, costs, yields, capacities and surplus pools are SYNTHETIC / illustrative. "
                       "Bridge hours are ESTIMATED from public qualification data. Mobility is MODELLED.",
    }
