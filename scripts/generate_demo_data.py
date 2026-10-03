"""Generate the SYNTHETIC demo dataset in data/demo/.

Nothing written here is a government statistic. District names and coordinates are
real; every demand series, seat count, yield, surplus pool, cost and capacity is
invented for the SIH demonstration and labelled SYNTHETIC wherever it is shown.

The Pune / Electric Vehicle Service Technician series was shaped (a growth trend with
a 3-year demand cycle) so that the forecast shortage is about 1,200 with a wide band.
The numbers the app shows are still computed by the forecast and optimiser from these
files, not stored anywhere.

Deterministic: fixed seeds, so re-running reproduces the committed files exactly.

    python scripts/generate_demo_data.py
"""
import json
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo"
MONTHS = pd.period_range("2021-10", periods=60, freq="M").astype(str)
STATE = "Maharashtra"

# district: (lat, lon of district headquarters, relative size of its labour market)
DISTRICTS = {
    "Pune": (18.5204, 73.8567, 1.00),
    "Thane": (19.2183, 72.9781, 0.80),
    "Nashik": (19.9975, 73.7898, 0.60),
    "Ahmednagar": (19.0948, 74.7480, 0.45),
    "Solapur": (17.6599, 75.9064, 0.40),
    "Satara": (17.6805, 74.0183, 0.35),
    "Raigad": (18.6414, 72.8722, 0.30),
}

# trade: (monthly openings in Pune at the start, annual growth, cycle amplitude, pipeline yield,
#         supply ratio = pipeline supply / demand: below 1 is a shortage trade, above 1 a surplus trade)
TRADES = {
    "Electric Vehicle Service Technician": (50, 0.12, 0.35, 0.32, 1.30),
    "Service Technician (Heavy Motor Vehicle)": (26, 0.05, 0.15, 0.40, 0.55),
    "Four Wheeler Service Technician": (40, 0.03, 0.10, 0.45, 1.35),
    "Four Wheeler Service Assistant": (18, 0.02, 0.10, 0.45, 1.30),
    "Two/Three-Wheeler Mechanic": (30, 0.02, 0.12, 0.45, 1.25),
    "Battery System Repair Technician": (14, 0.15, 0.20, 0.40, 0.50),
    "Battery System Assembly Operator": (10, 0.05, 0.15, 0.45, 1.30),
    "Electrician": (60, 0.05, 0.10, 0.50, 0.95),
}
EV = "Electric Vehicle Service Technician"
EV_OUTSIDE_PUNE = 0.25  # EV servicing demand is concentrated in Pune in this demo

# certified graduates not yet placed, available to bridge or to move (district, trade): count
SURPLUS = {
    ("Pune", "Four Wheeler Service Technician"): 400,
    ("Pune", "Four Wheeler Service Assistant"): 150,
    ("Pune", "Two/Three-Wheeler Mechanic"): 200,
    ("Pune", "Battery System Assembly Operator"): 120,
    ("Satara", EV): 180, ("Ahmednagar", EV): 200, ("Thane", EV): 150,
    ("Solapur", EV): 120, ("Nashik", EV): 160, ("Raigad", EV): 60,
    ("Thane", "Service Technician (Heavy Motor Vehicle)"): 90,
    ("Nashik", "Service Technician (Heavy Motor Vehicle)"): 70,
    ("Thane", "Four Wheeler Service Technician"): 220,
    ("Nashik", "Four Wheeler Service Technician"): 160,
    ("Satara", "Battery System Repair Technician"): 40,
}

INTERVENTIONS = [  # kind, cost per starter (INR), yield, lead time (months), capacity (starters)
    ("new_seats", 60000, 0.32, 13, 800),
    ("bridge", 15000, 0.75, 4, 400),
    ("neighbour", 10000, 0.60, 2, 250),
    ("apprenticeship", 18000, 0.80, 3, 250),
]

CAPACITIES = [  # per-cell overrides of the default capacity: district, trade, kind, starters
    ("Pune", "Service Technician (Heavy Motor Vehicle)", "new_seats", 300),
    ("Pune", "Service Technician (Heavy Motor Vehicle)", "apprenticeship", 80),
    ("Pune", "Battery System Repair Technician", "new_seats", 200),
    ("Pune", "Battery System Repair Technician", "apprenticeship", 60),
    ("Pune", "Battery System Repair Technician", "bridge", 150),
]

PARAMS = {
    "demo": {"state": STATE, "district": "Pune", "trade": EV, "budget": 60000000, "horizon": 18},
    "unmet_penalty": 300000,
    "adjacency_threshold": 0.6,
    "max_level_gap": 1,
    "mobility_decay_km": 150,
    "bridge_cost_per_hour": 50,
    "bridge_hours_per_month": 120,
    "placement_months": 1,
    "scenario_probabilities": {"LOW": 0.25, "MEDIAN": 0.5, "HIGH": 0.25},
}


def demand(seed, level, growth, amplitude, period=36, phase=np.pi / 2, noise=0.07):
    """Monthly openings: growth trend x demand cycle x noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(len(MONTHS))
    y = level * (1 + growth) ** (t / 12) * (1 + amplitude * np.sin(2 * np.pi * t / period + phase))
    return np.round(y * rng.lognormal(0, noise, len(t)))


def main():
    DEMO.mkdir(parents=True, exist_ok=True)
    history, training = [], []
    for district, (_, _, size) in DISTRICTS.items():
        for trade, (level, growth, amplitude, yield_, ratio) in TRADES.items():
            if (district, trade) == ("Pune", EV):
                series, seats = demand(1, level, growth, amplitude), 600
            else:
                scale = size * (EV_OUTSIDE_PUNE if trade == EV else 1)
                seed = zlib.crc32(f"{district}|{trade}".encode())  # stable across runs and platforms
                series = demand(seed, level * scale, growth, amplitude, phase=(seed % 628) / 100)
                # seats sized against the last year's demand, then scaled by the trade's supply ratio
                seats = int(round(ratio * series[-12:].sum() / yield_, -1))
            history += [(district, trade, m, int(v)) for m, v in zip(MONTHS, series)]
            training.append((district, trade, seats, yield_))

    pd.DataFrame([(STATE, d, lat, lon) for d, (lat, lon, _) in DISTRICTS.items()],
                 columns=["state", "district", "lat", "lon"]).to_csv(DEMO / "districts.csv", index=False)
    pd.DataFrame(history, columns=["district", "trade", "month", "openings"]).to_csv(DEMO / "demand_history.csv", index=False)
    pd.DataFrame(training, columns=["district", "trade", "annual_seats", "pipeline_yield"]).to_csv(DEMO / "training_capacity.csv", index=False)
    pd.DataFrame([(d, t, n) for (d, t), n in SURPLUS.items()],
                 columns=["district", "trade", "surplus"]).to_csv(DEMO / "surplus_pools.csv", index=False)
    pd.DataFrame(INTERVENTIONS, columns=["kind", "cost_per_starter", "yield", "lead_time_months", "capacity"]).to_csv(DEMO / "interventions.csv", index=False)
    pd.DataFrame(CAPACITIES, columns=["district", "trade", "kind", "capacity"]).to_csv(DEMO / "capacities.csv", index=False)
    (DEMO / "params.json").write_text(json.dumps(PARAMS, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(history)} demand rows for {len(training)} district-trade cells to {DEMO}")


if __name__ == "__main__":
    main()
