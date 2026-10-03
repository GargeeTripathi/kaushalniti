"""Skill Gap Resolver: scenario linear programme over intervention pathways.

Pure optimisation, no I/O. See docs/methodology.md for the formulation.

A *pathway* is one concrete way to supply one shortage cell: new seats, an
apprenticeship, a bridge course from one source trade, or supply from one
neighbouring district. Several pathways (and several cells) may draw on the same
surplus pool, and all of them share one budget.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linprog

KINDS = ("new_seats", "bridge", "neighbour", "apprenticeship")
SCENARIOS = ("LOW", "MEDIAN", "HIGH")


@dataclass
class Pathway:
    id: str
    kind: str                      # one of KINDS
    cell: tuple                    # (district, trade) being supplied
    cost: float                    # k: rupees per starter
    yield_: float                  # y: share of starters who become workers
    lead: int                      # L: months until workers are delivered
    cap: float                     # upper bound on starters for this pathway
    pool: tuple | None = None      # shared surplus pool key (district, trade)
    detail: dict = field(default_factory=dict)


@dataclass
class Problem:
    cells: list                    # [(district, trade)]
    demand: dict                   # {cell: {scenario: D}}
    baseline: dict                 # {cell: S0}
    pathways: list                 # [Pathway]
    kind_caps: dict                # {(kind, cell): U}
    pools: dict                    # {pool key: P}
    budget: float
    horizon: int
    penalty: float                 # pi: rupees per unmet worker

    def gap(self, cell, scenario):
        return max(0.0, self.demand[cell][scenario] - self.baseline[cell])

    def in_time(self, p):
        return p.lead <= self.horizon


def solve(problem, weights):
    """Minimise sum_s w_s * penalty * unmet(c,s) + cost, for scenario weights w.

    Pass {"LOW": 1} for a single-scenario plan or probabilities for the expected plan.
    Returns (starters per pathway as floats, optimal objective).
    """
    P, cells, scen = problem.pathways, problem.cells, list(weights)
    n = len(P)
    u_index = {(c, s): n + i for i, (c, s) in enumerate((c, s) for c in cells for s in scen)}
    nvar = n + len(u_index)

    obj = np.zeros(nvar)
    obj[:n] = [p.cost for p in P]
    for (c, s), i in u_index.items():
        obj[i] = problem.penalty * weights[s]

    rows, rhs = [], []

    def add(coeffs, bound):
        row = np.zeros(nvar)
        for i, v in coeffs:
            row[i] += v
        rows.append(row)
        rhs.append(bound)

    for (c, s), ui in u_index.items():  # residual gap: -sum(y x) - u <= -(D - S0)
        add([(i, -p.yield_) for i, p in enumerate(P) if p.cell == c] + [(ui, -1.0)], -problem.gap(c, s))
    add([(i, p.cost) for i, p in enumerate(P)], problem.budget)  # budget
    for (kind, c), cap in problem.kind_caps.items():  # capacity U(i,c)
        add([(i, 1.0) for i, p in enumerate(P) if p.kind == kind and p.cell == c], cap)
    for key, size in problem.pools.items():  # shared surplus pools
        users = [(i, 1.0) for i, p in enumerate(P) if p.pool == key]
        if users:
            add(users, size)

    # deadline: a pathway that delivers after the horizon cannot be used
    bounds = [(0, p.cap if problem.in_time(p) else 0) for p in P] + [(0, None)] * len(u_index)
    res = linprog(obj, A_ub=np.array(rows), b_ub=np.array(rhs), bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"optimiser failed: {res.message}")
    return res.x[:n], float(res.fun)


def feasible(problem, x):
    """True if whole-number plan x respects budget, capacities and shared pools."""
    P = problem.pathways
    if cost(problem, x) > problem.budget + 1e-6:
        return False
    if any(xi > p.cap + 1e-6 or (xi > 0 and not problem.in_time(p)) for p, xi in zip(P, x)):
        return False
    for (kind, c), cap in problem.kind_caps.items():
        if sum(xi for p, xi in zip(P, x) if p.kind == kind and p.cell == c) > cap + 1e-6:
            return False
    return all(sum(xi for p, xi in zip(P, x) if p.pool == key) <= size + 1e-6 for key, size in problem.pools.items())


def round_plan(problem, x):
    """Whole starters. Round down (always feasible), then round a fraction up where nothing is violated."""
    plan = [float(math.floor(v + 1e-6)) for v in x]
    for i in sorted(range(len(plan)), key=lambda i: plan[i] - x[i]):  # largest fraction first
        if x[i] - plan[i] > 1e-6:
            plan[i] += 1
            if not feasible(problem, plan):
                plan[i] -= 1
    return plan


def supplied(problem, x, cell):
    return sum(p.yield_ * xi for p, xi in zip(problem.pathways, x) if p.cell == cell)


def cost(problem, x):
    return sum(p.cost * xi for p, xi in zip(problem.pathways, x))


def unmet(problem, x, cell, scenario):
    return max(0.0, problem.gap(cell, scenario) - supplied(problem, x, cell))


def evaluate(problem, x, scenario):
    """Cost of a plan plus the unmet-demand penalty if `scenario` happens."""
    return cost(problem, x) + problem.penalty * sum(unmet(problem, x, c, scenario) for c in problem.cells)


def timeline(problem, x, cell):
    """Cumulative workers delivered to `cell` by month 0..horizon.

    ponytail: each pathway delivers its whole cohort at its lead time (a step);
    spread cohorts over intake batches if monthly phasing matters.
    """
    return [round(float(sum(p.yield_ * xi for p, xi in zip(problem.pathways, x) if p.cell == cell and p.lead <= m)), 1)
            for m in range(problem.horizon + 1)]


def seats_only(problem, cell, scenario):
    """Baseline: close the gap with new training seats alone (given the whole budget)."""
    p = next(p for p in problem.pathways if p.kind == "new_seats" and p.cell == cell)
    gap = problem.gap(cell, scenario)
    required = math.ceil(gap / p.yield_ - 1e-9) if gap > 0 else 0
    capacity = min(p.cap, problem.kind_caps.get(("new_seats", cell), math.inf))
    limits = {
        "need": required,
        "capacity": math.floor(capacity),
        "budget": math.floor(problem.budget / p.cost),
        "deadline": required if problem.in_time(p) else 0,
    }
    seats = min(limits.values())
    workers = p.yield_ * seats
    x = [seats if q is p else 0 for q in problem.pathways]
    return {
        "seats_required": required,
        "cost_required": required * p.cost,
        "capacity": limits["capacity"],
        "lead_time_months": p.lead,
        "seats_feasible": seats,
        "cost": seats * p.cost,
        "workers_delivered": workers,
        "residual_gap": max(0.0, gap - workers),
        "binding": [k for k in ("capacity", "budget", "deadline") if limits[k] == seats and seats < required],
        "timeline": timeline(problem, x, cell),
    }


def classify(plans):
    """Split each pathway's starters into no-regret (needed in every scenario) and contingent."""
    out = []
    for i in range(len(next(iter(plans.values())))):
        qty = {s: float(x[i]) for s, x in plans.items()}
        lo, hi = min(qty.values()), max(qty.values())
        label = ("NOT_USED" if hi == 0 else "CONTINGENT" if lo == 0
                 else "NO_REGRET" if lo == hi else "MIXED")
        out.append({"by_scenario": qty, "no_regret_starters": lo, "contingent_starters": hi - lo, "class": label})
    return out


def binding_constraints(problem, x, cell, scenario):
    """Which real constraints explain a residual gap. Read off the solved plan, not invented."""
    reasons = []
    if unmet(problem, x, cell, scenario) < 1:
        return reasons
    P = problem.pathways
    kind_used = {(k, c): sum(xi for p, xi in zip(P, x) if (p.kind, p.cell) == (k, c)) for k, c in problem.kind_caps}
    pool_used = {key: sum(xi for p, xi in zip(P, x) if p.pool == key) for key in problem.pools}

    def headroom(p, xi):  # starters this pathway could still take, ignoring money
        room = [p.cap - xi, problem.kind_caps.get((p.kind, p.cell), math.inf) - kind_used.get((p.kind, p.cell), 0)]
        if p.pool in problem.pools:
            room.append(problem.pools[p.pool] - pool_used[p.pool])
        return min(room)

    spare = problem.budget - cost(problem, x)
    open_paths = [p for p, xi in zip(P, x) if p.cell == cell and problem.in_time(p) and headroom(p, xi) >= 1]
    if open_paths and spare < min(p.cost for p in open_paths):
        reasons.append({"constraint": "budget", "detail": "the budget is fully committed"})
    for kind in KINDS:
        cap = problem.kind_caps.get((kind, cell))
        used = kind_used.get((kind, cell), 0)
        if cap is not None and used >= math.floor(cap) and cap > 0:
            reasons.append({"constraint": "capacity", "kind": kind, "detail": f"{kind} capacity of {cap:,.0f} starters is used up"})
    for key, size in problem.pools.items():
        mine = any(p.pool == key and p.cell == cell for p in P)
        if mine and pool_used[key] >= math.floor(size) and size > 0:
            reasons.append({"constraint": "surplus", "pool": list(key), "detail": f"surplus pool {key[1]} in {key[0]} ({size:,.0f}) is exhausted"})
    for p in P:
        if p.cell == cell and not problem.in_time(p):
            reasons.append({"constraint": "deadline", "kind": p.kind, "detail": f"{p.id} needs {p.lead} months, beyond the {problem.horizon}-month horizon"})
    return reasons


def resolve(problem, probabilities):
    """Solve every scenario plus the probability-weighted plan; compare them."""
    plans, optimum = {}, {}
    for s in SCENARIOS:
        x, optimum[s] = solve(problem, {s: 1.0})
        plans[s] = round_plan(problem, x)
    expected, _ = solve(problem, probabilities)
    all_plans = {**plans, "EXPECTED": round_plan(problem, expected)}
    # regret: how much worse a plan is in scenario s than the best plan for s
    regret = {name: {s: max(0.0, evaluate(problem, x, s) - optimum[s]) for s in SCENARIOS}
              for name, x in all_plans.items()}
    return {"plans": all_plans, "optimum": optimum, "regret": regret, "classes": classify(plans)}
