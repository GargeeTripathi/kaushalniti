import pytest

from kaushalniti import adjacency as A


def qual(nqr_id, title, standards, applicability="STT"):
    return {"nqr_id": nqr_id, "title": title, "nsqf_level": 4, "applicability": applicability,
            "standards": [{"title": t, "code": c, "hours": h, "mandatory": True} for t, c, h in standards]}


GENERIC = [("Employability Skills (60 hours)", "DGT/VSQ/N0102 ,v1.0", 60), ("Organize work and resources (Service)", "ASC/N9801", 60),
           ("Apply health and safety practices at the workplace", "ELE/N1002", 30), ("OJT", "NA", 60)]
EV = qual(1, "EV Service Technician", GENERIC + [
    ("Carry out routine service or minor repairs on four wheeler electric vehicle", "ASC/N1450", 90),
    ("High voltage and fire safety practices", "ASC/N9846", 180)])
CAR = qual(2, "Four Wheeler Service Technician", GENERIC + [("Carry out routine service and minor repairs", "ASC/N1403", 210)])
TAILOR = qual(3, "Tailor", GENERIC + [("Stitch garments to customer measurements", "AMH/N1947", 200)])
TRAINER = qual(4, "EV Trainer", [("Carry out routine service or minor repairs on four wheeler electric vehicle", "ASC/N1450", 90)], "For TOT")
QUALS = [EV, CAR, TAILOR, TRAINER]


def test_clean_code_handles_register_formatting():
    assert A.clean_code("(ELE/N1002)") == "ELE/N1002"
    assert A.clean_code("DGT/VSQ/N0101, V.1.0") == "DGT/VSQ/N0101"
    assert A.clean_code("ASC/N9846 ,v1.0") == "ASC/N9846"
    assert A.clean_code("N/A") == "" and A.clean_code(None) == ""


def test_clean_text_strips_brackets_and_punctuation():
    assert A.clean_text("Employability Skills (60 Hours)") == "employability skills"
    assert A.clean_text("  Repair  faulty parts; in the Battery-System ") == "repair faulty parts in the battery-system"


def test_generic_standards_are_removed_but_technical_safety_is_kept():
    titles = [s["title"] for s in A.technical_standards(EV)]
    assert titles == ["Carry out routine service or minor repairs on four wheeler electric vehicle",
                      "High voltage and fire safety practices"]


def test_widely_reused_codes_are_treated_as_generic():
    many = [qual(i, f"Q{i}", [("Core practice of the sector", "XYZ/N1000", 30), (f"Specific task {i}", f"XYZ/N2{i:03d}", 90)])
            for i in range(40)]
    assert A.generic_codes(many) == {"XYZ/N1000"}
    assert [s["code"] for s in A.technical_standards(many[0], A.generic_codes(many))] == ["XYZ/N2000"]


@pytest.fixture(scope="module")
def edges():
    found, _ = A.build(QUALS, [1], "tfidf")
    return {e["source_id"]: e for e in found}


def test_adjacent_trade_scores_above_unrelated_trade(edges):
    assert 2 in edges and edges[2]["score"] == pytest.approx(90 / 270, abs=0.01)
    assert 3 not in edges  # no technical overlap: below the storage floor


def test_thresholding_splits_matched_and_unmatched(edges):
    e = edges[2]
    assert [m["code"] for m in e["matched"]] == ["ASC/N1450"]
    assert [u["code"] for u in e["unmatched"]] == ["ASC/N9846"]
    assert e["matched"][0]["similarity"] >= A.MATCH_THRESHOLD["tfidf"] > e["unmatched"][0]["best_similarity"]


def test_bridge_hours_are_unmatched_hours_plus_top_up(edges):
    e = edges[2]
    expected = 180 + 90 * (1 - e["matched"][0]["similarity"])
    assert e["bridge_hours"] == round(expected) and e["status"] == "ESTIMATED"


def test_same_standard_code_is_an_exact_match():
    twin = qual(5, "Other EV role", [("Service an electric car", "ASC/N1450", 90)])
    found, _ = A.build([EV, twin], [1], "tfidf")
    assert found[0]["matched"][0]["similarity"] == 1.0


def test_trainer_qualifications_are_not_sources(edges):
    assert 4 not in edges
