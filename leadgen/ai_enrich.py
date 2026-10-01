"""AI website understanding, with proof.

For each lead's own website, an LLM extracts: is it a flexible-workspace operator, what type,
which space types it offers, and which customers it targets. EVERY claim must carry an exact
quote from the page; claims whose quote is not really on the page are dropped (anti-hallucination).
The deterministic score is not changed by this step.
"""
import argparse
import hashlib
import html
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests

from . import llm,scoring

UA = "CoworkingLeadResearch/0.1 (student project; reads public pages only)"
TEXT_DIR = Path("data/page_text")
MAX_CHARS = 8000
MIN_CHARS = 300

OPERATOR_TYPES = ("independent", "chain_branch", "landlord_or_business_centre", "unclear")
SPACE_TYPES = ("hot_desk", "dedicated_desk", "private_cabin", "private_office", "meeting_room",
               "conference_room", "day_pass", "virtual_office", "event_space", "training_room",
               "managed_office")
CUSTOMERS = ("freelancers", "startups", "smes", "enterprises", "students", "agencies")

PROMPT = """You extract facts about a coworking / flexible-office business from the text of its own website.
Rules:
- Use ONLY the website text below. Never use outside knowledge.
- Every answer needs a "quote": an exact, word-for-word copy of a short phrase (max 20 words) from the text that proves it.
- If the text does not clearly say it, leave it out (value null, or an empty list).
- private_cabin means cabins; private_office means "private office spaces"; do not swap them.
- List a customer type only if the text names that type or a close synonym ("large organizations" means enterprises). "Growing teams" alone is NOT startups or smes.
- Use operator_type "independent" only if the text shows one brand running its own spaces and mentions no other cities or franchises; otherwise use "unclear".
Return ONLY JSON in exactly this shape:
{{
  "is_flexible_workspace_operator": {{"value": true or false or null, "quote": "..."}},
  "operator_type": {{"value": one of {op_types} or null, "quote": "..."}},
  "space_types": [{{"value": one of {spaces}, "quote": "..."}}],
  "target_customers": [{{"value": one of {customers}, "quote": "..."}}]
}}
Meaning of operator_type: independent = a single-brand operator running its own spaces;
chain_branch = a branch of a multi-city or national brand; landlord_or_business_centre = a building owner or
serviced-office / business centre that is not focused on coworking; unclear = cannot tell.

Business name: {name}
Website text:
\"\"\"{text}\"\"\"
"""


# ---------- page text (polite, cached) ----------
_robots = {}
_last_hit = {}


def allowed(url):
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": UA}, timeout=8)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except Exception:
            rp.parse([])
        _robots[base] = rp
    return _robots[base].can_fetch(UA, url)


def html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()[:MAX_CHARS]


def page_text(url):
    """Visible text of the home page, or None. Cached on disk (delete data/page_text to retry)."""
    path = TEXT_DIR / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".txt")
    if path.exists():
        return path.read_text(encoding="utf-8") or None
    text = ""
    try:
        if allowed(url):
            host = urlparse(url).netloc
            wait = 1.0 - (time.time() - _last_hit.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            r = requests.get(url, headers={"User-Agent": UA}, timeout=12)
            _last_hit[host] = time.time()
            if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
                text = html_to_text(r.text)
    except Exception:
        text = ""
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text or None


# ---------- validation: the anti-hallucination guard ----------
def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def quote_ok(quote, text_norm):
    q = norm(quote)
    return len(q) >= 8 and q in text_norm


def validate(raw, text):
    """Keep only claims whose quote really appears in the page. Returns (profile, stats)."""
    tn = norm(text)
    stats = Counter()
    profile = {"is_operator": None, "operator_type": None, "space_types": [],
               "target_customers": [], "evidence": {}}
    if not isinstance(raw, dict):
        return profile, stats

    def check(item, allowed_values):
        if not isinstance(item, dict):
            return None
        stats["claims"] += 1
        value, quote = item.get("value"), item.get("quote")
        if value is None or value not in allowed_values or not quote or not quote_ok(quote, tn):
            stats["dropped"] += 1
            return None
        return value, quote

    got = check(raw.get("is_flexible_workspace_operator"), (True, False))
    if got:
        profile["is_operator"] = got[0]
        profile["evidence"]["is_operator"] = got[1]
    got = check(raw.get("operator_type"), OPERATOR_TYPES)
    if got:
        profile["operator_type"] = got[0]
        profile["evidence"]["operator_type"] = got[1]
    for key, allowed_values, field in (("space_types", SPACE_TYPES, "space_types"),
                                       ("target_customers", CUSTOMERS, "target_customers")):
        items = raw.get(key)
        for item in items if isinstance(items, list) else []:
            got = check(item, allowed_values)
            if got and got[0] not in profile[field]:
                profile[field].append(got[0])
                profile["evidence"][got[0]] = got[1]
    return profile, stats


# ---------- run over all leads ----------
def run(src="data/leads_enriched.json", dst="data/leads_ai.json", limit=None):
    leads = json.loads(Path(src).read_text(encoding="utf-8"))
    status = Counter()
    totals = Counter()
    attempted = 0
    shown = 0
    for lead in leads:
        lead["ai_profile"] = None
        lead["ai_flag"] = None
        if not scoring.is_complete(lead):
            lead["ai_status"] = "skipped_incomplete"
        elif not lead.get("website"):
            lead["ai_status"] = "no_website"
        else:
            text = page_text(lead["website"])
            if not text:
                lead["ai_status"] = "fetch_failed_or_blocked"
            elif len(text) < MIN_CHARS:
                lead["ai_status"] = "too_little_text"
            elif limit is not None and attempted >= limit:
                lead["ai_status"] = "not_run_limit"
            else:
                attempted += 1
                print(f"[{attempted}] {lead['company_name']}", flush=True)
                prompt = PROMPT.format(
                    op_types=list(OPERATOR_TYPES), spaces=list(SPACE_TYPES), customers=list(CUSTOMERS),
                    name=lead["company_name"], text=text)
                raw = llm.ask_json(prompt)
                if raw is None:
                    lead["ai_status"] = "llm_failed_or_no_key"
                else:
                    profile, stats = validate(raw, text)
                    totals.update(stats)
                    lead["ai_profile"] = profile
                    lead["ai_status"] = "ok"
                    if profile["is_operator"] is False:
                        lead["ai_flag"] = "likely_not_operator"
                    prov = dict(lead.get("data_provenance") or {})
                    for k in ("is_operator", "operator_type", "space_types", "target_customers"):
                        if profile[k] not in (None, []):
                            prov[k] = "ai_inferred_quote_verified"
                    lead["data_provenance"] = prov
                    if shown < 5:
                        shown += 1
                        print(f"  operator: {profile['is_operator']} | type: {profile['operator_type']}")
                        print(f"  spaces: {profile['space_types']} | customers: {profile['target_customers']}")
        status[lead["ai_status"]] += 1

    Path(dst).write_text(json.dumps(leads, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nstatus:", dict(status))
    print(f"claims checked: {totals['claims']}, dropped (quote not on page): {totals['dropped']}")
    print("operator types:", dict(Counter(
        (l["ai_profile"] or {}).get("operator_type") for l in leads if l["ai_profile"])))
    print("flagged likely_not_operator:", sum(1 for l in leads if l["ai_flag"]))
    print("wrote", dst)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only call the LLM for N leads (trial run)")
    a = ap.parse_args()
    run(limit=a.limit)