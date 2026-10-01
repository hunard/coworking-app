"""Why are two records merged? Run: python -m leadgen.debug_pair"""
import json
from .cleaning import clean_record, linked, name_sim, addr_sim

raw = json.load(open("data/raw_leads.json", encoding="utf-8"))
a = next(clean_record(r) for r in raw if (r.get("place_id") or "").endswith("BUwzjpws"))
b = next(clean_record(r) for r in raw if (r.get("place_id") or "").endswith("xBxunWes"))
print("phones:", a["phone"], a["phone_type"], "|", b["phone"], b["phone_type"])
print("name_sim:", round(name_sim(a["_key"], b["_key"]), 2))
print("addr_sim:", round(addr_sim(a["address"], b["address"]), 2))
print("linked:", linked(a, b))
