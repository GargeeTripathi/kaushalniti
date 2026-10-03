"""Data layer: loads the versioned demo dataset and assembles optimiser problems.

Everything is read from local files, so the app runs offline. Which numbers are
REAL, SYNTHETIC, MODELLED or ESTIMATED is recorded in data/metadata/datasets.json
and repeated on every assumption returned by the API.
"""
import json
import math
import os
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import forecast
from .adjacency import eligibility, load_edges
from .resolver import KINDS, Pathway, Problem

DATA_DIR = Path(os.environ.get("KAUSHALNITI_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))


class NotFound(LookupError):
    """Unknown state, district or trade, or no data for the requested cell."""


def km(a, b):
    """Great-circle distance between two (lat, lon) points."""
    (la1, lo1), (la2, lo2) = (map(math.radians, p) for p in (a, b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


class Store:
    def __init__(self, root=DATA_DIR):
        demo = Path(root) / "demo"
        self.districts = pd.read_csv(demo / "districts.csv")
        self.trades = pd.read_csv(demo / "trades.csv")
        self.history = pd.read_csv(demo / "demand_history.csv")
        self.training = pd.read_csv(demo / "training_capacity.csv")
        self.surplus = pd.read_csv(demo / "surplus_pools.csv")
        self.interventions = pd.read_csv(demo / "interventions.csv").set_index("kind")
        self.capacities = pd.read_csv(demo / "capacities.csv")
        self.params = json.loads((demo / "params.json").read_text(encoding="utf-8"))
        self.datasets = json.loads((Path(root) / "metadata" / "datasets.json").read_text(encoding="utf-8"))
        self.adjacency = load_edges(Path(root) / "processed" / "adjacency.json")
        self.coords = {r.district: (r.lat, r.lon) for r in self.districts.itertuples()}
        self.state_of = dict(zip(self.districts.district, self.districts.state))
        self.nqr_id = dict(zip(self.trades.trade, self.trades.nqr_id))
        self.trade_of = {v: k for k, v in self.nqr_id.items()}
        self.pool = {(r.district, r.trade): float(r.surplus) for r in self.surplus.itertuples()}
        self._scenarios = {}

    # ---- lookups -------------------------------------------------------
    def check(self, district, trade, state=None):
        if district not in self.coords:
            raise NotFound(f"unknown district '{district}'")
        if state and self.state_of[district] != state:
            raise NotFound(f"district '{district}' is not in state '{state}'")
        if trade not in self.nqr_id:
            raise NotFound(f"unknown trade '{trade}'")
        if self.series(district, trade).empty:
            raise NotFound(f"no demand data for {trade} in {district}")

    def series(self, district, trade):
        h = self.history
        return h[(h.district == district) & (h.trade == trade)].sort_values("month")

    def cells(self, state=None):
        pairs = self.history[["district", "trade"]].drop_duplicates()
        return [(d, t) for d, t in pairs.itertuples(index=False) if not state or self.state_of[d] == state]

    # ---- demand, supply, gap -------------------------------------------
    def scenarios(self, district, trade, horizon):
        key = (district, trade, horizon)
        if key not in self._scenarios:
            self._scenarios[key] = forecast.scenarios(self.series(district, trade).openings.tolist(), horizon)
        return self._scenarios[key]

    def baseline(self, district, trade, horizon):
        """S0: workers the existing training pipeline delivers within the horizon."""
        t = self.training
        row = t[(t.district == district) & (t.trade == trade)]
        if row.empty:
            return 0.0
        return float(row.annual_seats.iloc[0] * row.pipeline_yield.iloc[0] * horizon / 12)

    def gap(self, district, trade, horizon):
        sc, s0 = self.scenarios(district, trade, horizon), self.baseline(district, trade, horizon)
        return {
            "district": district, "trade": trade, "state": self.state_of[district], "horizon": horizon,
            "demand": {s: round(sc[s]) for s in ("LOW", "MEDIAN", "HIGH")},
            "baseline_supply": round(s0),
            "shortage": {s: max(0, round(sc[s] - s0)) for s in ("LOW", "MEDIAN", "HIGH")},
            "surplus": round(self.pool.get((district, trade), 0)),  # unplaced graduates available to bridge or move
        }

    # ---- parameters ----------------------------------------------------
    def settings(self, overrides=None):
        """Intervention parameters and model constants, with any planner overrides applied."""
        o = overrides or {}
        iv = {k: {"cost": float(r.cost_per_starter), "yield": float(r["yield"]), "lead": int(r.lead_time_months),
                  "capacity": float(r.capacity)} for k, r in self.interventions.iterrows()}
        changes = o.get("interventions") or {}
        for kind, fields in changes.items():
            iv[kind].update({k: v for k, v in fields.items() if v is not None})
        p = {**self.params, **{k: v for k, v in o.items() if k != "interventions" and v is not None}}
        capacity_overridden = {k for k, fields in changes.items() if fields.get("capacity") is not None}
        return iv, p, capacity_overridden

    def capacity(self, kind, cell, iv, overridden):
        """U(i,c): a per-cell figure if the dataset has one, unless the planner overrode it."""
        c = self.capacities
        row = c[(c.district == cell[0]) & (c.trade == cell[1]) & (c.kind == kind)]
        return iv[kind]["capacity"] if row.empty or kind in overridden else float(row.capacity.iloc[0])

    def bridge_edges(self, trade):
        """Adjacency edges into `trade` from other demo trades."""
        target = self.nqr_id[trade]
        return [e for e in self.adjacency["edges"] if e["target_id"] == target and e["source_id"] in self.trade_of]

    # ---- optimiser problem ---------------------------------------------
    def problem(self, cells, budget, horizon, overrides=None):
        iv, p, overridden = self.settings(overrides)
        pathways, kind_caps, demand, baseline, skipped = [], {}, {}, {}, []
        for cell in cells:
            district, trade = cell
            sc = self.scenarios(district, trade, horizon)
            demand[cell] = {s: sc[s] for s in ("LOW", "MEDIAN", "HIGH")}
            baseline[cell] = self.baseline(district, trade, horizon)
            for kind in KINDS:
                kind_caps[(kind, cell)] = self.capacity(kind, cell, iv, overridden)

            for kind in ("new_seats", "apprenticeship"):
                a = iv[kind]
                pathways.append(Pathway(kind, kind, cell, a["cost"], a["yield"], a["lead"], kind_caps[(kind, cell)]))

            b = iv["bridge"]
            for e in self.bridge_edges(trade):
                source = self.trade_of[e["source_id"]]
                pool = self.pool.get((district, source), 0.0)
                info = {"source_trade": source, "score": e["score"], "bridge_hours": e["bridge_hours"], "pool": pool}
                blocked = eligibility(e, p["adjacency_threshold"], p["max_level_gap"])
                if pool <= 0:
                    blocked.append("no surplus in district")
                if blocked:
                    skipped.append({"cell": list(cell), "kind": "bridge", **info, "reason": "; ".join(blocked)})
                    continue
                hours = e["bridge_hours"]
                if hours:  # cost and duration follow the estimated bridge hours
                    cost = hours * p["bridge_cost_per_hour"]
                    lead = math.ceil(hours / p["bridge_hours_per_month"]) + p["placement_months"]
                else:
                    cost, lead = b["cost"], b["lead"]
                pathways.append(Pathway(f"bridge:{source}", "bridge", cell, cost, b["yield"], lead, pool,
                                        pool=(district, source), detail=info))

            n = iv["neighbour"]
            for other, where in self.coords.items():
                pool = self.pool.get((other, trade), 0.0)
                if other == district or pool <= 0 or self.state_of[other] != self.state_of[district]:
                    continue
                dist = km(self.coords[district], where)
                reach = math.exp(-dist / p["mobility_decay_km"])  # MODELLED distance decay, not observed flows
                pathways.append(Pathway(f"neighbour:{other}", "neighbour", cell, n["cost"], n["yield"], n["lead"],
                                        math.floor(reach * pool), pool=(other, trade),
                                        detail={"source_district": other, "distance_km": round(dist), "reach": round(reach, 3), "pool": pool}))
        pools = {p_.pool: self.pool[p_.pool] for p_ in pathways if p_.pool}
        problem = Problem(cells, demand, baseline, pathways, kind_caps, pools, budget, horizon, p["unmet_penalty"])
        return problem, iv, p, skipped


@lru_cache(maxsize=1)
def store():
    return Store()
