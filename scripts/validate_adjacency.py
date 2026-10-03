"""Compare the bridgeability graph with reviewed judgements.

data/metadata/adjacency_validation.csv holds source/target qualification pairs with a
reviewer's accept/reject and reason. This script re-reads the current graph, fills in
the model columns and prints how often the model's eligibility agrees with the review.

    python scripts/validate_adjacency.py

The committed judgements are an AI-assisted desk review, not a subject-expert review.
Replace the `accepted` and `reason` columns with expert judgements to make this a real validation.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from kaushalniti.adjacency import eligibility  # noqa: E402

SHEET = ROOT / "data" / "metadata" / "adjacency_validation.csv"


def main():
    graph = json.loads((ROOT / "data" / "processed" / "adjacency.json").read_text(encoding="utf-8"))
    params = json.loads((ROOT / "data" / "demo" / "params.json").read_text(encoding="utf-8"))
    edges = {(e["source_id"], e["target_id"]): e for e in graph["edges"]}
    sheet = pd.read_csv(SHEET)
    found = [edges.get(pair) for pair in zip(sheet.source_id, sheet.target_id)]
    sheet["model_score"] = [e["score"] if e else 0.0 for e in found]
    sheet["bridge_hours"] = [e["bridge_hours"] if e else None for e in found]
    sheet["model_eligible"] = ["yes" if e and not eligibility(e, params["adjacency_threshold"], params["max_level_gap"]) else "no"
                               for e in found]
    sheet.to_csv(SHEET, index=False)

    model, human = sheet.model_eligible == "yes", sheet.accepted == "yes"
    tp, fp, fn, tn = (model & human).sum(), (model & ~human).sum(), (~model & human).sum(), (~model & ~human).sum()
    print(f"{len(sheet)} pairs | agree {tp + tn} ({(tp + tn) / len(sheet):.0%})")
    print(f"model eligible & accepted {tp} | model eligible & rejected {fp} | model not eligible & accepted {fn} | both no {tn}")
    print(f"precision {tp / max(1, tp + fp):.0%} | recall {tp / max(1, tp + fn):.0%}")


if __name__ == "__main__":
    main()
