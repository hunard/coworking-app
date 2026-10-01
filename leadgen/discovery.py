"""Discover businesses from Google Maps through SerpApi (one query per area, 20 results per page)."""
import os
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv
from .cache import get_or_fetch

load_dotenv()
API_URL = "https://serpapi.com/search.json"

# approximate centre points (lat, lng) so each query searches a different part of Mumbai
AREAS = {
    "Andheri": (19.1197, 72.8468), "BKC Bandra": (19.0674, 72.8689),
    "Lower Parel": (18.9930, 72.8300), "Powai": (19.1176, 72.9060),
    "Goregaon": (19.1663, 72.8526), "Malad": (19.1860, 72.8480),
    "Worli": (19.0176, 72.8180), "Vikhroli": (19.1100, 72.9270),
    "Ghatkopar": (19.0860, 72.9080), "Nariman Point": (18.9256, 72.8242),
    "Chembur": (19.0622, 72.8975), "Borivali": (19.2307, 72.8567),
}


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


def search_area(area, category="coworking space", city="Mumbai", max_pages=2):
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        raise RuntimeError("SERPAPI_KEY missing: check your .env file")
    lat, lng = AREAS[area]
    out = []
    for page in range(max_pages):
        params = {"engine": "google_maps", "type": "search", "q": f"{category} in {area}, {city}",
                  "ll": f"@{lat},{lng},14z", "start": page * 20, "hl": "en", "api_key": api_key}
        items = get_or_fetch(params, _call).get("local_results", [])
        out += [parse(i) for i in items]
        if len(items) < 20:     # last page
            break
    return out


def discover(areas=None, **kw):
    out = []
    for a in (areas or list(AREAS)):
        out += search_area(a, **kw)
    return out


if __name__ == "__main__":
    import sys, json
    leads = discover() if "--all" in sys.argv else discover(["Andheri"], max_pages=1)
    os.makedirs("data", exist_ok=True)
    with open("data/raw_leads.json", "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=1)
    print("saved", len(leads), "raw records to data/raw_leads.json")
    print("with phone:", sum(1 for l in leads if l["phone"]))
    print("with website:", sum(1 for l in leads if l["website"]))