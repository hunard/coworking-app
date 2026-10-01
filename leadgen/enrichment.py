"""Enrichment: read each business's OWN website and extract public contact info.

Rules-only (no LLM). Everything found on the page is labelled with where it came from.
Politeness: robots.txt respected, 1s delay per host, timeouts, honest User-Agent.
We never bypass blocks: a 403/429/CAPTCHA page is recorded as "blocked" and skipped.

Email policy (a wrong email is worse than a missing one). An email becomes the lead's
contact only if it is:
  1. on the business's own domain            -> website_scraped
  2. on a closely related domain (same brand) -> website_scraped_related_domain
  3. on a free provider such as gmail         -> website_scraped_free_provider
Anything else (web designers, plugins) goes to emails_other as unverified.
"""
import argparse
import hashlib
import html as htmllib
import json
import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

UA = "CoworkingLeadsBot/0.1 (internship assignment prototype; github.com/hunard)"
TIMEOUT = 10
PAGE_CACHE = Path("cache/pages")
SOCIAL_HOSTS = ("facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com")

SERVICES = {
    "hot_desk": r"hot[\s-]?desk",
    "dedicated_desk": r"dedicated (desk|seat|workstation)",
    "private_cabin": r"private (cabin|office)|\bcabins?\b",
    "meeting_room": r"meeting rooms?|conference rooms?|board ?room",
    "day_pass": r"day[\s-]?pass",
    "virtual_office": r"virtual office",
    "event_space": r"event (space|hall)|events? & training|training rooms?",
    "open_24x7": r"24\s*[/x*]\s*7|24 hours",
    "parking": r"\bparking\b",
    "cafeteria": r"cafeteria|pantry|caf[eé]\b",
}

SOCIAL_PATTERNS = {
    "linkedin": r"linkedin\.com/(company|in|school)/",
    "facebook": r"facebook\.com/(?!sharer|share|tr\?|plugins|dialog)",
    "instagram": r"instagram\.com/(?!p/|explore|accounts)",
    "x": r"(twitter|x)\.com/(?!intent|share|home)",
    "youtube": r"youtube\.com/(channel|c|user|@)",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
JUNK_DOMAINS = {"example.com", "domain.com", "yourdomain.com", "email.com", "sentry.io",
                "wixpress.com", "sentry-next.wixpress.com", "godaddy.com"}
JUNK_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "js", "css", "woff", "woff2"}
JUNK_LOCAL = {"name", "yourname", "your", "email", "test", "user", "john", "someone"}
GOOD_PREFIX = ("info", "hello", "contact", "sales", "enquiry", "enquiries", "support", "bookings", "connect")
FREE_PROVIDERS = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com",
                  "yahoo.in", "yahoo.co.in", "rediffmail.com", "live.com", "icloud.com"}
SECOND_LEVELS = {"co", "com", "org", "net", "gov", "ac", "edu"}

_host_lock = threading.Lock()
_host_last = {}
_robots = {}


# ---------- fetching (polite, cached, never bypasses blocks) ----------

def _wait_for_host(host):
    with _host_lock:
        now = time.time()
        wait = max(0.0, _host_last.get(host, 0) + 1.0 - now)
        _host_last[host] = now + wait
    if wait:
        time.sleep(wait)


def robots_allows(url):
    parts = urlparse(url)
    root = f"{parts.scheme}://{parts.netloc}"
    if root not in _robots:
        rp = RobotFileParser()
        try:
            r = requests.get(root + "/robots.txt", headers={"User-Agent": UA}, timeout=8)
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
                _robots[root] = rp
            else:
                _robots[root] = None  # no robots file means allowed
        except requests.RequestException:
            _robots[root] = None
    rp = _robots[root]
    return True if rp is None else rp.can_fetch(UA, url)


def fetch_page(url):
    """Return {"url", "status", "html"}. status: ok / blocked / robots_disallowed / error."""
    PAGE_CACHE.mkdir(parents=True, exist_ok=True)
    path = PAGE_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    result = {"url": url, "status": "error", "html": ""}
    try:
        if not robots_allows(url):
            result["status"] = "robots_disallowed"
        else:
            _wait_for_host(urlparse(url).netloc)
            r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
            body = r.text[:500_000]
            low = body[:20000].lower()
            ctype = r.headers.get("content-type", "")
            if r.status_code in (401, 403, 429) or "captcha" in low or "cf-challenge" in low:
                result["status"] = "blocked"
            elif r.status_code >= 400:
                result["status"] = "error"
            elif "html" not in ctype:
                result["status"] = "error"
            else:
                result.update(status="ok", html=body, url=r.url)
    except requests.RequestException:
        result["status"] = "error"
    path.write_text(json.dumps(result), encoding="utf-8")
    return result


# ---------- extraction (pure functions, easy to test) ----------

def visible_text(html):
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", htmllib.unescape(text)).lower()


def reg_domain(host):
    """Registrable domain: www.foo.co.in -> foo.co.in, mail.foo.com -> foo.com."""
    labels = [p for p in host.lower().split(":")[0].split(".") if p]
    if len(labels) >= 3 and labels[-2] in SECOND_LEVELS and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def brand_label(host):
    """Brand part of a domain: www.wework.co.in -> wework, empire-offices.com -> empireoffices."""
    return reg_domain(host).split(".")[0].replace("-", "")


def related_brand(a, b):
    """True if two brand labels clearly belong together (same, prefix, or long shared start)."""
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 4 and long_.startswith(short):
        return True
    return len(os.path.commonprefix([a, b])) >= 6


def extract_emails(html):
    """All plausible emails on the page (junk removed). Not yet trusted."""
    found = []
    for m in EMAIL_RE.findall(htmllib.unescape(html)):
        email = m.lower().strip(".")
        local, _, domain = email.partition("@")
        tld = domain.rsplit(".", 1)[-1]
        if not tld.isalpha() or len(tld) < 2:  # drops package versions like leaflet@1.7.1
            continue
        if domain in JUNK_DOMAINS or local in JUNK_LOCAL or tld in JUNK_TLDS:
            continue
        if email not in found:
            found.append(email)
    return found


def classify_emails(emails, site_hosts):
    """Split emails into (own, related, free, other). Only the first three may become the contact."""
    own_domains = {reg_domain(h) for h in site_hosts if h}
    own_brands = {brand_label(h) for h in site_hosts if h}
    own, related, free, other = [], [], [], []
    for e in emails:
        domain = e.partition("@")[2]
        if reg_domain(domain) in own_domains:
            own.append(e)
        elif domain in FREE_PROVIDERS:
            free.append(e)
        elif any(related_brand(brand_label(domain), b) for b in own_brands):
            related.append(e)
        else:
            other.append(e)

    def pref(e):
        return 0 if e.partition("@")[0].startswith(GOOD_PREFIX) else 1

    return (sorted(own, key=pref)[:5], sorted(related, key=pref)[:3],
            sorted(free, key=pref)[:3], other[:5])


def extract_socials(html):
    socials = {}
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I):
        for name, pattern in SOCIAL_PATTERNS.items():
            if name not in socials and re.search(pattern, href, flags=re.I):
                socials[name] = href.split("?")[0].rstrip("/")
    return socials


def extract_services(html):
    text = visible_text(html)
    return sorted(name for name, pat in SERVICES.items() if re.search(pat, text))


def find_contact_url(html, base_url):
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I):
        if "contact" in href.lower() and not href.lower().startswith(("mailto:", "tel:")):
            full = urljoin(base_url, href.split("#")[0])
            if urlparse(full).netloc == urlparse(base_url).netloc:
                return full
    return None


# ---------- per-lead enrichment ----------

def enrich_lead(lead, fetch=fetch_page):
    out = dict(lead)
    out["email"] = None  # never trust an old email; it is re-derived below
    prov = {k: v for k, v in (out.get("data_provenance") or {}).items() if k != "email"}
    for field in ("company_name", "phone", "address", "website", "rating", "review_count", "maps_url"):
        if out.get(field):
            prov[field] = "google_maps_via_serpapi"
    out.update(emails_all=[], emails_other=[], social_links={}, services=[], fetch_status="no_website")

    site = out.get("website")
    if site:
        host = urlparse(site).netloc.lower()
        if any(host.endswith(s) for s in SOCIAL_HOSTS):
            out["fetch_status"] = "social_only"
            out["social_links"] = {host.replace("www.", "").split(".")[0]: site}
            prov["social_links"] = "website_scraped"
        else:
            home = fetch(site)
            out["fetch_status"] = home["status"]
            if home["status"] == "ok":
                pages = [home["html"]]
                contact_url = find_contact_url(home["html"], home["url"])
                if contact_url and contact_url != home["url"]:
                    contact = fetch(contact_url)
                    if contact["status"] == "ok":
                        pages.append(contact["html"])
                combined = "\n".join(pages)

                hosts = {host, urlparse(home["url"]).netloc.lower()}
                own, related, free, other = classify_emails(extract_emails(combined), hosts)
                out["emails_all"] = own + related + free
                out["emails_other"] = other
                if own:
                    out["email"], prov["email"] = own[0], "website_scraped"
                elif related:
                    out["email"], prov["email"] = related[0], "website_scraped_related_domain"
                elif free:
                    out["email"], prov["email"] = free[0], "website_scraped_free_provider"

                out["social_links"] = extract_socials(combined)
                out["services"] = extract_services(combined)
                if out["social_links"]:
                    prov["social_links"] = "website_scraped"
                if out["services"]:
                    prov["services"] = "website_scraped"
    out["data_provenance"] = prov
    return out


def run(src="data/leads_filtered.json", dst="data/leads_enriched.json", limit=None, workers=6):
    leads = json.loads(Path(src).read_text(encoding="utf-8"))
    if limit:
        leads = leads[:limit]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        enriched = list(pool.map(enrich_lead, leads))
    Path(dst).write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")

    src_count = Counter(l["data_provenance"].get("email") for l in enriched)
    print("fetch status:", dict(Counter(l["fetch_status"] for l in enriched)))
    print("email own domain:", src_count["website_scraped"])
    print("email related domain:", src_count["website_scraped_related_domain"])
    print("email free provider:", src_count["website_scraped_free_provider"])
    print("leads with rejected other-domain emails:", sum(1 for l in enriched if l["emails_other"]))
    print("with social links:", sum(1 for l in enriched if l["social_links"]))
    print("with services:", sum(1 for l in enriched if l["services"]))
    print("complete (phone or email):", sum(1 for l in enriched if l.get("phone") or l.get("email")))
    print("wrote", dst)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    run(limit=args.limit)