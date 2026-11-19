"""Data sources. Each source returns a list of Item records; the collector does the change tracking.

Add a source: write a fetch function that returns Items, then add it to SOURCES with a country code.
All sources here are official open-data endpoints (no scraping), checked 2026-11-19.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Callable

import requests

UA = {"User-Agent": "civic-hub/0.1 (+https://github.com/planb438/homelab)"}
TIMEOUT = 30


@dataclass
class Item:
    key: str                      # stable id inside the source
    title: str
    value: object                 # anything JSON-serialisable; compared to detect changes
    url: str = ""
    number: float | None = None   # numeric form for charts (days, %, $...)


@dataclass
class Source:
    id: str
    name: str
    country: str
    category: str
    url: str
    fetch: Callable[[], list[Item]]
    track_removed: bool = True    # feeds that rotate (news) should not report "removed"
    notes: str = ""
    tags: list[str] = field(default_factory=list)


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*(day|week|month|year)s?", re.I)
_FACTOR = {"day": 1, "week": 7, "month": 30, "year": 365}


def to_days(text: object) -> float | None:
    """'33 days' -> 33, '3 weeks' -> 21, 'No processing time available' -> None."""
    if not isinstance(text, str):
        return None
    m = _DUR.search(text)
    return float(m.group(1)) * _FACTOR[m.group(2).lower()] if m else None


# ---------------------------------------------------------------- IRCC processing times
IRCC_BASE = "https://www.canada.ca/content/dam/ircc/documents/json/"
IRCC_PAGE = "https://www.canada.ca/en/immigration-refugees-citizenship/services/application/check-processing-times.html"
IRCC_LABELS = {
    "visitor-outside-canada": "Visitor visa (outside Canada)",
    "supervisa": "Super visa",
    "study": "Study permit (outside Canada)",
    "work": "Work permit (outside Canada)",
    "child_dependent": "Citizenship/PR – dependent child",
    "child_adopted": "Adopted child",
    "refugees_gov": "Government-assisted refugees",
    "refugees_private": "Privately sponsored refugees",
}


def _country_names() -> dict[str, str]:
    names = _get(IRCC_BASE + "data-country-name-en.json").json().get("country-name", {})
    return {k: html.unescape(v) for k, v in names.items()}


def fetch_ircc_by_country() -> list[Item]:
    data = _get(IRCC_BASE + "data-ptime-en.json").json()
    names = _country_names()
    items = []
    for cat, per_country in data.items():
        if not isinstance(per_country, dict):
            continue
        label = IRCC_LABELS.get(cat, cat)
        for cc, val in per_country.items():
            title = f"{label} — {names.get(cc, cc)}"
            if isinstance(val, dict):          # e.g. refugees_private: {sponsor, refugee}
                for sub, v in val.items():
                    items.append(Item(f"{cat}/{cc}/{sub}", f"{title} ({sub})", v, IRCC_PAGE, to_days(v)))
            else:
                items.append(Item(f"{cat}/{cc}", title, val, IRCC_PAGE, to_days(val)))
    return items


IRCC_IN_CANADA_LABELS = {
    "visitor_inside_canada": "Visitor visa (applying in Canada)", "visitor_extension": "Visitor record (extend stay)",
    "study_extension": "Study permit extension", "work_extension": "Work permit extension",
    "iec": "International Experience Canada", "iec_past": "IEC (previous season)",
    "eta": "eTA (electronic travel authorization)", "new_pr": "PR card (new)", "existing_pr": "PR card (renewal)",
    "replacement": "Replacement document", "amend_imm": "Amend immigration document", "amend_tr": "Amend temporary resident document",
    "cit_search": "Citizenship record search", "cit_renunciation": "Renounce citizenship", "cit_resumption": "Resume citizenship",
    "cit_adoption_part1": "Citizenship for adopted child (part 1)", "cit_adoption_part2": "Citizenship for adopted child (part 2)",
    "cit_proof": "Citizenship certificate (proof)", "cit_grant": "Citizenship grant",
    "sawp_current": "Seasonal Agricultural Worker Program", "skilled_trades_ee": "Federal Skilled Trades (Express Entry)",
}


def _label(key: str) -> str:
    return IRCC_IN_CANADA_LABELS.get(key) or key.replace("_", " ").replace("-", " ").capitalize()


def fetch_ircc_in_canada() -> list[Item]:
    data = _get(IRCC_BASE + "data-ptime-non-country-en.json").json()
    items = []
    for group, entries in data.items():
        if group == "default-update" or not isinstance(entries, dict):
            continue
        for k, v in entries.items():
            if isinstance(v, (str, int, float)):
                items.append(Item(f"{group}/{k}", _label(k), v, IRCC_PAGE, to_days(v)))
    return items


# ---------------------------------------------------------------- Canada.ca news
NEWS_URL = "https://api.io.canada.ca/io-server/gc/news/en/v2?sort=publishedDate&orderBy=desc&pick=50&format=json"


def fetch_gc_news() -> list[Item]:
    entries = _get(NEWS_URL).json().get("feed", {}).get("entry", [])
    return [Item(e["link"], e.get("title", "").strip(),
                 {"published": e.get("publishedDate"), "teaser": (e.get("teaser") or "").strip()},
                 e["link"]) for e in entries if e.get("link")]


# ---------------------------------------------------------------- Statistics Canada (WDS)
STATCAN_WDS = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
STATCAN_VECTORS = {
    41690973: ("Consumer Price Index, all-items (2002=100)", "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401"),
    2062815: ("Unemployment rate, 15+ (seasonally adjusted, %)", "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701"),
    1: ("Population estimate, Canada (quarterly)", "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1710000901"),
}


def fetch_statcan() -> list[Item]:
    body = [{"vectorId": v, "latestN": 1} for v in STATCAN_VECTORS]
    r = requests.post(STATCAN_WDS, json=body, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    items = []
    for row in r.json():
        if row.get("status") != "SUCCESS":
            continue
        obj = row["object"]
        pt = obj["vectorDataPoint"][-1]
        title, url = STATCAN_VECTORS.get(obj["vectorId"], (f"Vector {obj['vectorId']}", ""))
        items.append(Item(f"v{obj['vectorId']}", title, {"period": pt["refPer"], "value": pt["value"]}, url, float(pt["value"])))
    return items


# ---------------------------------------------------------------- Bank of Canada (Valet)
BOC_SERIES = {"V39079": "Bank of Canada policy rate (%)", "FXUSDCAD": "USD/CAD exchange rate"}


def fetch_boc() -> list[Item]:
    items = []
    for s, title in BOC_SERIES.items():
        obs = _get(f"https://www.bankofcanada.ca/valet/observations/{s}/json?recent=1").json()["observations"][-1]
        val = float(obs[s]["v"])
        items.append(Item(s, title, {"date": obs["d"], "value": val}, f"https://www.bankofcanada.ca/valet/observations/{s}", val))
    return items


# ---------------------------------------------------------------- open.canada.ca
OPEN_URL = "https://open.canada.ca/data/api/action/package_search?rows=25&sort=metadata_modified%20desc"


def fetch_open_canada() -> list[Item]:
    res = _get(OPEN_URL).json()["result"]["results"]
    out = []
    for p in res:
        t = p.get("title_translated", {}).get("en") or p.get("title") or p["name"]
        org = (p.get("organization") or {}).get("title", "")
        out.append(Item(p["id"], t, {"modified": p.get("metadata_modified"), "org": org.split("|")[0].strip()},
                        f"https://open.canada.ca/data/en/dataset/{p['id']}"))
    return out


SOURCES: list[Source] = [
    Source("ca-ircc-country", "IRCC processing times (by country)", "ca", "immigration", IRCC_PAGE, fetch_ircc_by_country,
           tags=["Ask Canada"]),
    Source("ca-ircc-incanada", "IRCC processing times (in Canada)", "ca", "immigration", IRCC_PAGE, fetch_ircc_in_canada,
           tags=["Ask Canada"]),
    Source("ca-gc-news", "Canada.ca news", "ca", "news", "https://www.canada.ca/en/news.html", fetch_gc_news,
           track_removed=False),
    Source("ca-statcan", "Statistics Canada indicators", "ca", "economy", "https://www.statcan.gc.ca", fetch_statcan),
    Source("ca-boc", "Bank of Canada", "ca", "economy", "https://www.bankofcanada.ca/rates/", fetch_boc),
    Source("ca-open-data", "open.canada.ca — recently updated datasets", "ca", "open-data", "https://open.canada.ca/data/en/",
           fetch_open_canada, track_removed=False),
]


def by_country(country: str) -> list[Source]:
    return [s for s in SOURCES if s.country == country]


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
