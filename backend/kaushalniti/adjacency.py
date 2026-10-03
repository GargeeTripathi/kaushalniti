"""Bridgeability graph from Indian qualification data (National Qualifications Register).

For a source and a target qualification we compare their *technical* occupational
standards. Generic standards (employability, safety, teamwork...) are removed first:
they are shared by almost every qualification and would make everything look adjacent.

    score        = share of the target's technical hours covered by a matching source standard
    bridge hours = hours of unmatched target standards
                   + hours x (1 - similarity) for matched ones               (ESTIMATED)

Skill adjacency is established prior art; this module only applies it to Indian
qualification data so that it can feed the resolver.

Build the cached edge file (run once, result is committed):

    python -m kaushalniti.adjacency                 # sentence-transformers if installed, else TF-IDF
    python -m kaushalniti.adjacency --method tfidf
"""
import argparse
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parents[2] / "data"
QUALIFICATIONS = DATA / "processed" / "qualifications.json"
EDGES = DATA / "processed" / "adjacency.json"

ST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# a target standard counts as covered when its best source match reaches this cosine similarity
MATCH_THRESHOLD = {"sentence-transformers": 0.60, "tfidf": 0.35}
KEEP_SCORE = 0.10        # edges weaker than this are not stored
TOP_SOURCES = 25         # strongest sources kept per target
GENERIC_SHARE = 0.04     # a standard used by more than this share of qualifications is generic

# Code series are not a reliable signal (e.g. ASC/N9846 is high-voltage safety, a core EV skill),
# so generic standards are found by title and by how widely a code is reused.
GENERIC_CODE = re.compile(r"DGT/VSQ|MSME/ES", re.I)
GENERIC_TITLE = re.compile(
    r"employab|health,? (and|&) safety|workplace safety|safe and secure|"
    r"work effectively|team|communicat|soft skill|entrepreneur|housekeeping|"
    r"organi[sz]e work|plan and organi[sz]e|interpersonal|gender|sustainab|greening|"
    r"on[- ]the[- ]job|\bojt\b|internship|project work|introduction module|induction", re.I)
# trainer and assessor qualifications describe teaching the trade, not doing it
NOT_A_TRADE = {"For TOT", "For TOA"}
CODE = re.compile(r"[A-Z]{2,5}(?:/[A-Z]{2,4})?/N\d{3,4}")


def clean_code(raw):
    """'(ELE/N1002)' and 'DGT/VSQ/N0101, V.1.0' -> 'ELE/N1002', 'DGT/VSQ/N0101'; '' if there is none."""
    m = CODE.search((raw or "").upper().replace(" ", ""))
    return m.group(0) if m else ""


def clean_text(title):
    """Standard title without hour counts, version tags and punctuation noise."""
    t = re.sub(r"\(.*?\)", " ", title or "")
    t = re.sub(r"[^A-Za-z0-9&/+ -]", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def generic_codes(quals):
    """Codes used by so many qualifications that they cannot be technical."""
    seen = Counter(c for q in quals for c in {clean_code(s["code"]) for s in q["standards"]} if c)
    limit = max(3, GENERIC_SHARE * len(quals))
    return {c for c, n in seen.items() if n > limit}


def technical_standards(qual, frequent=frozenset()):
    """The standards that say what the job technically is."""
    out = []
    for s in qual["standards"]:
        code, text = clean_code(s["code"]), clean_text(s["title"])
        if not text or code in frequent or GENERIC_CODE.search(code) or GENERIC_TITLE.search(text):
            continue
        out.append({"code": code, "title": s["title"], "text": text,
                    "hours": s["hours"] or 0.0, "mandatory": s["mandatory"]})
    return out


def embed(texts, method):
    """Unit-length vectors, so a dot product is the cosine similarity."""
    if method == "sentence-transformers":
        from sentence_transformers import SentenceTransformer
        return np.asarray(SentenceTransformer(ST_MODEL).encode(texts, normalize_embeddings=True, show_progress_bar=False))
    from sklearn.feature_extraction.text import TfidfVectorizer
    return TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit_transform(texts).toarray()


def edge(source, target, src_std, tgt_std, vec, threshold):
    """Compare one source qualification with one target qualification."""
    if not src_std or not tgt_std:
        return None
    sim = vec[[s["i"] for s in tgt_std]] @ vec[[s["i"] for s in src_std]].T
    matched, unmatched = [], []
    for row, t in zip(sim, tgt_std):
        # the same standard code in the source is an exact match; otherwise the closest text
        hit = next((s for s in src_std if t["code"] and s["code"] == t["code"]), None)
        if hit:
            best = 1.0
        else:
            j = int(row.argmax())
            hit, best = src_std[j], float(row[j])
        item = {"code": t["code"], "title": t["title"], "hours": t["hours"]}
        if best >= threshold:
            matched.append({**item, "source_code": hit["code"], "source_title": hit["title"], "similarity": round(best, 3)})
        else:
            unmatched.append({**item, "best_similarity": round(best, 3)})
    total = sum(t["hours"] for t in tgt_std)
    if total <= 0:  # no hours published: fall back to counting standards
        score = len(matched) / len(tgt_std)
        bridge_hours = None
    else:
        score = sum(m["hours"] for m in matched) / total
        # unmatched standards are taught in full; matched ones still need a top-up in proportion
        # to how far the source standard is from the target one
        bridge_hours = round(sum(u["hours"] for u in unmatched) + sum(m["hours"] * (1 - m["similarity"]) for m in matched))
    return {
        "source_id": source["nqr_id"], "source": source["title"],
        "target_id": target["nqr_id"], "target": target["title"],
        "score": round(score, 3),
        "bridge_hours": bridge_hours,
        "target_technical_hours": total,
        "matched": matched, "unmatched": unmatched,
        "source_level": source["nsqf_level"], "target_level": target["nsqf_level"],
        "source_sector": source.get("sector"), "target_sector": target.get("sector"),
        "status": "ESTIMATED",
    }


def build(quals, target_ids, method):
    """Edges from every qualification into each target qualification."""
    quals = [q for q in quals if q["applicability"] not in NOT_A_TRADE or q["nqr_id"] in target_ids]
    frequent = generic_codes(quals)
    std = {q["nqr_id"]: technical_standards(q, frequent) for q in quals}
    texts = sorted({s["text"] for ss in std.values() for s in ss})
    index = {t: i for i, t in enumerate(texts)}
    vec = embed(texts, method)
    for ss in std.values():
        for s in ss:
            s["i"] = index[s["text"]]
    by_id = {q["nqr_id"]: q for q in quals}
    edges = []
    for tid in target_ids:
        found = [e for q in quals if q["nqr_id"] != tid
                 and (e := edge(q, by_id[tid], std[q["nqr_id"]], std[tid], vec, MATCH_THRESHOLD[method]))
                 and e["score"] >= KEEP_SCORE]
        edges += sorted(found, key=lambda e: (-e["score"], e["source_id"]))[:TOP_SOURCES]
    return edges, frequent


def eligibility(e, threshold, max_level_gap):
    """Why an edge may not feed the optimiser; an empty list means it is eligible.

    Text similarity alone gives false positives when standards are worded generically
    (a CNC programmer also 'assists in routine maintenance'), so two plain guards apply.
    """
    reasons = []
    if e["score"] < threshold:
        reasons.append(f"adjacency {e['score']:.0%} is below the {threshold:.0%} threshold")
    if e.get("source_sector") != e.get("target_sector"):
        reasons.append("source and target are in different sectors")
    if None not in (e["source_level"], e["target_level"]) and e["target_level"] - e["source_level"] > max_level_gap:
        reasons.append(f"source is more than {max_level_gap:g} NSQF level below the target")
    return reasons


def pick_method():
    try:
        import sentence_transformers  # noqa: F401
        return "sentence-transformers"
    except ImportError:
        return "tfidf"


def load_edges(path=EDGES):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {"edges": []}


def main():
    import pandas as pd
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--method", choices=list(MATCH_THRESHOLD), default=pick_method())
    args = ap.parse_args()
    register = json.loads(QUALIFICATIONS.read_text(encoding="utf-8"))
    trades = pd.read_csv(DATA / "demo" / "trades.csv")
    edges, frequent = build(register["qualifications"], [int(i) for i in trades["nqr_id"]], args.method)
    EDGES.write_text(json.dumps({
        "method": args.method,
        "model": ST_MODEL if args.method == "sentence-transformers" else "TF-IDF (1-2 grams) over standard titles",
        "match_threshold": MATCH_THRESHOLD[args.method],
        "status": "ESTIMATED from REAL / PUBLIC qualification data; not validated by subject experts",
        "source": register["source"],
        "register_scraped_on": register["scraped_on"],
        "built_on": date.today().isoformat(),
        "generic_codes_removed_by_frequency": sorted(frequent),
        "edges": edges,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(edges)} edges for {len(trades)} target trades using {args.method} -> {EDGES}")


if __name__ == "__main__":
    main()
