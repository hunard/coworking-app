"""Normalise fields and remove duplicates.

Merge two records only if a rule is true AND the record matches EVERY member of the group
(complete linkage, so A-B and B-C can never chain into A-C):
  R1 same Google place_id
  R2 same direct phone (not toll-free) AND similar name (>=0.6) AND building-address overlap (>=0.4)
  R3 very similar name (>=0.88) AND building-address overlap (>=0.5)
Same website alone is NOT enough: a chain's branches share a website but are different places.
"""
import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlparse

NOISE = r"\b(co[- ]?working|cowork|space|spaces|pvt|private|ltd|limited|llp|india|mumbai|the|best|in)\b"

GENERIC = {
    "mumbai", "maharashtra", "india", "road", "marg", "floor", "level", "wing", "tower",
    "building", "complex", "park", "business", "centre", "center", "office", "unit", "plot",
    "near", "opp", "opposite", "behind", "east", "west", "north", "south", "ground",
    "street", "suite", "block", "bkc", "andheri", "bandra", "kurla", "lower", "parel",
    "powai", "goregaon", "malad", "worli", "vikhroli", "ghatkopar", "chembur", "borivali",
    "nariman", "point", "next", "above", "industrial", "estate",
}


def strip_invisible(s):
    """Remove zero-width characters and normalise odd unicode (e.g. fancy fonts)."""
    if not s:
        return s
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_phone(p):
    if not p:
        return None
    d = re.sub(r"\D", "", str(p))
    if d.startswith("91") and len(d) > 10:
        d = d[2:]
    elif d.startswith("0"):
        d = d[1:]
    if d.startswith(("1800", "1860")):
        return f"+91{d}"
    return f"+91{d}" if len(d) == 10 else None


def phone_type(p):
    if not p:
        return None
    if p.startswith(("+911800", "+911860")):
        return "toll_free"
    return "mobile" if p[3] in "6789" else "landline"


def display_name(n):
    """'SPARTAN COWORK - BEST CO-WORKING ...' -> 'Spartan Cowork'"""
    n = strip_invisible(n)
    if not n:
        return None
    n = re.split(r"\s[-|–—]\s", n)[0].strip()
    return n.title() if n.isupper() else n


def name_key(n):
    n = re.sub(r"[^a-z0-9 ]", " ", (display_name(n) or "").lower())
    return re.sub(r"\s+", " ", re.sub(NOISE, " ", n)).strip()


def clean_url(u):
    if not u:
        return None
    p = urlparse(u if u.startswith("http") else "https://" + u)
    if not p.netloc:
        return None
    return f"https://{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}"


def tokens(a):
    """Building-specific words only: drop area names, generic words, floor and suite numbers."""
    toks = set(re.findall(r"[a-z0-9]{3,}", (a or "").lower()))
    return {t for t in toks if t not in GENERIC and not re.fullmatch(r"\d{1,4}|\d+(st|nd|rd|th)", t)}


def addr_sim(a, b):
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def name_sim(a, b):
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def clean_record(r):
    r = dict(r)
    r["company_name"] = display_name(r.pop("name", None))
    r["_key"] = name_key(r["company_name"])
    r["phone"] = clean_phone(r.get("phone"))
    r["phone_type"] = phone_type(r["phone"])
    r["website"] = clean_url(r.get("website"))
    r["address"] = strip_invisible(r.get("address")) or None
    r["review_count"] = int(r.get("review_count") or 0)
    return r


def linked(a, b):
    if a.get("place_id") and a["place_id"] == b.get("place_id"):
        return True
    ns = name_sim(a["_key"], b["_key"])
    as_ = addr_sim(a["address"], b["address"])
    shared_phone = a["phone"] and a["phone"] == b["phone"] and a.get("phone_type") != "toll_free"
    if shared_phone and ns >= 0.6 and as_ >= 0.4:
        return True
    return ns >= 0.88 and as_ >= 0.5


def merge(group):
    group.sort(key=lambda r: -sum(v not in (None, "", 0) for v in r.values()))
    m = dict(group[0])
    for g in group[1:]:
        for k, v in g.items():
            if m.get(k) in (None, "") and v not in (None, ""):
                m[k] = v
    m["merged_records"] = len(group)
    m["_members"] = [(g.get("place_id"), g["address"], g["phone"]) for g in group]
    return m


def dedupe(records):
    recs = [clean_record(r) for r in records]
    groups = []
    for r in recs:
        for g in groups:
            if all(linked(r, m) for m in g):
                g.append(r)
                break
        else:
            groups.append([r])
    out = [merge(g) for g in groups]
    for m in out:
        key = m.get("place_id") or f"{m['_key']}|{m['address']}"
        m["lead_id"] = "L" + hashlib.sha1(key.encode()).hexdigest()[:10]
    return out


def is_complete(r):
    return bool(r.get("company_name")) and bool(r.get("phone") or r.get("email"))


if __name__ == "__main__":
    from collections import Counter

    raw = json.load(open("data/raw_leads.json", encoding="utf-8"))
    out = dedupe(raw)
    print(f"raw={len(raw)}  unique={len(out)}  duplicates removed={len(raw) - len(out)}")
    print("incomplete (no name or no phone/email):", sum(not is_complete(r) for r in out))
    print("phone types:", Counter(r.get("phone_type") for r in out))
    print("\nCategories:", Counter(r.get("category") for r in out).most_common(8))
    print("\nMerged groups:")
    for r in out:
        if r["merged_records"] > 1:
            print(f"  {r['company_name']}  <- {r['merged_records']} records")
    print("\nNear misses (similar names, NOT merged):")
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            if name_sim(out[i]["_key"], out[j]["_key"]) >= 0.8:
                print(f"  {out[i]['company_name']} | {(out[i]['address'] or '')[:40]}")
                print(f"  {out[j]['company_name']} | {(out[j]['address'] or '')[:40]}\n")
    json.dump(out, open("data/clean_leads.json", "w", encoding="utf-8"), indent=1)