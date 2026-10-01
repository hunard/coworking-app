"""Discover businesses from Google Maps through SerpApi.

Inputs: city + business category (+ optional list of areas). One query per area,
20 results per page. For cities without configured area coordinates we fall back to
one city-wide query. Responses are cached on disk, so repeat runs cost no quota.
"""
import argparse
import json
import os
import re
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from .cache import get_or_fetch

load_dotenv()
API_URL = "https://serpapi.com/search.json"

# approximate centre points (lat, lng) so each query searches a different part of a city
AREAS = {
    "Andheri": (19.1197, 72.8468), "BKC Bandra": (19.0674, 72.8689),
    "Lower Parel": (18.9930, 72.8300), "Powai": (19.1176, 72.9060),
    "Goregaon": (19.1663, 72.8526), "Malad": (19.1860, 72.8480),
    "Worli": (19.0176, 72.8180), "Vikhroli": (19.1100, 72.9270),
    "Ghatkopar": (19.0860, 72.9080), "Nariman Point": (18.9256, 72.8242),
    "Chembur": (19.0622, 72.8975), "Borivali": (19.2307, 72.8567),
}

# add a city here (lowercase name -> {area: (lat, lng)}) to get multi-area coverage
CITY_AREAS = {"mumbai": AREAS}

DEFAULT_CITY = "Mumbai"
DEFAULT_CATEGORY = "coworking space"


def _call(params):
    r = requests.get(API_URL, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def parse(item):
    pid = item.get("place_id")
    return {
        "name": item.get("title"),
        "category": item.get("type"),
        "address": item.get("address"),
        "phone": item.get("phone"),
        "email": None,   # Google Maps does not provide email; enrichment will look for it
        "website": item.get("website"),
        "maps_url": f"https://www.google.com/maps/place/?q=place_id:{pid}" if pid else None,
        "place_id": pid,
        "rating": item.get("rating"),
        "review_count": item.get("reviews"),
        "source": "google_maps_via_serpapi",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def search_area(area, category=DEFAULT_CATEGORY, city=DEFAULT_CITY, max_pages=2):
    """Search one area of a city. area=None means a single city-wide search."""
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        raise RuntimeError("SERPAPI_KEY missing: check your .env file")

    coords = CITY_AREAS.get(city.lower(), {}).get(area) if area else None
    query = f"{category} in {area}, {city}" if area else f"{category} in {city}"
    out = []
    for page in range(max_pages):
        params = {"engine": "google_maps", "type": "search", "q": query}
        if coords:
            params["ll"] = f"@{coords[0]},{coords[1]},14z"
        params.update({"start": page * 20, "hl": "en", "api_key": api_key})
        items = get_or_fetch(params, _call).get("local_results", [])
        out += [parse(i) for i in items]
        if len(items) < 20:     # last page
            break
    return out


def discover(city=DEFAULT_CITY, category=DEFAULT_CATEGORY, areas=None, max_pages=2):
    known = CITY_AREAS.get(city.lower())
    if known:
        chosen = areas or list(known)
        unknown = [a for a in chosen if a not in known]
        if unknown:
            raise ValueError(f"No coordinates for {unknown}. Known areas: {list(known)}")
    else:
        chosen = [None]  # unknown city: one city-wide query
        print(f"No area list for {city}: running one city-wide search.")
    out = []
    for a in chosen:
        out += search_area(a, category=category, city=city, max_pages=max_pages)
    return out


def default_output(city, category):
    if city.lower() == DEFAULT_CITY.lower() and category == DEFAULT_CATEGORY:
        return "data/raw_leads.json"  # the file the rest of the pipeline reads
    slug = re.sub(r"[^a-z0-9]+", "_", f"{city}_{category}".lower()).strip("_")
    return f"data/raw_{slug}.json"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Discover businesses via SerpApi (Google Maps).")
    ap.add_argument("--city", default=DEFAULT_CITY)
    ap.add_argument("--category", default=DEFAULT_CATEGORY)
    ap.add_argument("--areas", nargs="+", help="subset of configured areas, e.g. Andheri Powai")
    ap.add_argument("--all", action="store_true", help="search every configured area")
    ap.add_argument("--max-pages", type=int, default=2)
    ap.add_argument("--out", help="output file (default depends on city and category)")
    args = ap.parse_args()

    if args.all:
        areas = None
    elif args.areas:
        areas = args.areas
    else:
        areas = ["Andheri"]  # safe default: one area, one page budget-friendly
        args.max_pages = 1

    leads = discover(args.city, args.category, areas, args.max_pages)
    out = args.out or default_output(args.city, args.category)
    os.makedirs("data", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=1)
    print(f"saved {len(leads)} raw records to {out}")
    print("with phone:", sum(1 for l in leads if l["phone"]))
    print("with website:", sum(1 for l in leads if l["website"]))