"""Scrape qualification records from the National Qualifications Register (nqr.gov.in).

Fetches every qualification listed under the chosen sectors, caches the raw HTML in
data/raw/nqr/ (not committed) and writes the parsed records to
data/processed/qualifications.json (committed, so the app never needs the live site).

    python scripts/scrape_nqr.py                # default sectors
    python scripts/scrape_nqr.py --sectors 4 35 # by NQR sector id

Stdlib only. One request every DELAY seconds; cached pages are not re-fetched.
"""
import argparse
import html
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "nqr"
OUT = ROOT / "data" / "processed" / "qualifications.json"
BASE = "https://nqr.gov.in"
UA = "Mozilla/5.0 (KaushalNiti SIH student project; polite scraper)"
DELAY = 0.6
# NQR sector ids: 4 Automotive, 7 Capital Goods & Manufacturing, 11 Electronics & HW, 35 Power
DEFAULT_SECTORS = [4, 7, 11, 35]

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
opener.addheaders = [("User-Agent", UA)]


def get(url, data=None, headers=None, tries=3):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    for attempt in range(tries):
        try:
            with opener.open(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:  # network hiccup: back off and retry
            if attempt == tries - 1:
                raise
            print(f"  retry {url}: {e}")
            time.sleep(3 * (attempt + 1))


def sector_ids(sector):
    """Qualification ids for one sector, via the site's own listing endpoint."""
    page = get(f"{BASE}/qualifications-search/{sector}")
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    body = urllib.parse.urlencode({
        "_token": token, "offset": 0, "limit": 5000, "sectorId": sector, "getId": sector,
        "currentroute": "qualifications-search", "table_name": "", "count": 0,
    }).encode()
    listing = get(f"{BASE}/filter-duration", data=body, headers={
        "X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/qualifications-search/{sector}"})
    return sorted({int(i) for i in re.findall(r'class="getQualificationIds" value="(\d+)"', listing)})


def tokens(page):
    """Visible text nodes of the page, in order."""
    page = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", "", page, flags=re.S)
    parts = (html.unescape(t).strip() for t in re.split(r"<[^>]+>", page))
    return [re.sub(r"\s+", " ", t) for t in parts if t]


def after(toks, label, start=0):
    for i in range(start, len(toks) - 1):
        if toks[i].rstrip(":").strip().lower() == label.lower():
            return toks[i + 1]
    return None


def num(text):
    m = re.search(r"\d+(\.\d+)?", text or "")
    return float(m.group(0)) if m else None


def parse(qid, page):
    toks = tokens(page)
    title = after(toks, "Qualifications Search")
    if not title:
        return None
    standards = []
    table = re.search(r"Learning Module In Job Role.*?<table>(.*?)</table>", page, flags=re.S)
    for row in re.findall(r"<tr>(.*?)</tr>", table.group(1) if table else "", flags=re.S):
        c = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", x))).strip()
             for x in re.findall(r"<td>(.*?)</td>", row, flags=re.S)]
        if len(c) != 6:
            continue
        code = re.match(r"(.*?)\s*(?:\((v[\d.]+)\))?$", c[1])
        standards.append({
            "title": c[0], "code": code.group(1).strip(), "version": code.group(2),
            "mandatory": c[2].lower().startswith("mandatory"), "requirement": c[2],
            "hours": num(c[3]), "credits": num(c[4]), "level": num(c[5]),
        })
    sec_at = next((i for i, t in enumerate(toks) if t == "Sector"), 0)
    valid = next((t for t in toks if t.startswith("Valid Till")), "")
    max_hours = next((t for t in toks if t.startswith("Maximum :")), "")
    nqr_code = after(toks, "NQR Code") or ""
    return {
        "nqr_id": qid,
        "source_url": f"{BASE}/qualifications/{qid}",
        "title": title,
        "nqr_code": nqr_code.split(" & ")[0].strip(),
        "version": (re.search(r"Version\s*([\d.]+)", nqr_code) or [None, None])[1],
        "sector": after(toks, "Sector", sec_at),
        "nsqf_level": num(after(toks, "Level", sec_at)),
        "notional_hours": num(max_hours),
        "occupation": after(toks, "Proposed Occupation"),
        "awarding_body": after(toks, "Awarding Bodies"),
        "qualification_type": after(toks, "Qualifcation Type"),
        "applicability": after(toks, "Qualifcation By Applicability"),
        "approved_on": after(toks, "Originally Approved"),
        "valid_till": (re.search(r"\d{2}/\d{2}/\d{4}", valid) or [None])[0],
        "job_description": after(toks, "Job Description"),
        "standards": standards,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sectors", type=int, nargs="+", default=DEFAULT_SECTORS)
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)

    ids = []
    for s in args.sectors:
        found = sector_ids(s)
        print(f"sector {s}: {len(found)} qualifications")
        ids += found
        time.sleep(DELAY)

    records = []
    for n, qid in enumerate(sorted(set(ids)), 1):
        cache = RAW / f"{qid}.html"
        if cache.exists():
            page = cache.read_text(encoding="utf-8")
        else:
            try:
                page = get(f"{BASE}/qualifications/{qid}")
            except Exception as e:
                print(f"  skip {qid}: {e}")
                continue
            cache.write_text(page, encoding="utf-8")
            time.sleep(DELAY)
        rec = parse(qid, page)
        if rec and rec["standards"]:
            records.append(rec)
        if n % 50 == 0:
            print(f"  {n}/{len(set(ids))} pages, {len(records)} parsed")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "National Qualifications Register, NCVET (https://nqr.gov.in)",
        "status": "REAL / PUBLIC (scraped; may lag the live register)",
        "scraped_on": date.today().isoformat(),
        "sectors": args.sectors,
        "qualifications": records,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(records)} qualifications to {OUT}")


if __name__ == "__main__":
    main()
