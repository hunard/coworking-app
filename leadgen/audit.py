"""Quality checks on cleaning. Run: python -m leadgen.audit"""
import json
from .cleaning import clean_phone

raw = json.load(open("data/raw_leads.json", encoding="utf-8"))
clean = json.load(open("data/clean_leads.json", encoding="utf-8"))

# Check 1: is our phone cleaner throwing away real numbers?
with_phone = [r["phone"] for r in raw if r.get("phone")]
rejected = [p for p in with_phone if not clean_phone(p)]
print(f"raw records with a phone: {len(with_phone)}/{len(raw)}")
print(f"phones our cleaner rejected: {len(rejected)}  examples: {rejected[:8]}")

# Check 2: merges where the records had DIFFERENT place_ids (the risky ones)
print("\nRisky merges (different place_ids merged together):")
for r in clean:
    members = r.get("_members", [])
    if len({m[0] for m in members}) > 1:
        print(f"- {r['company_name']}")
        for pid, addr, phone in members:
            print("     ", (pid or "")[-8:], "|", (addr or "")[:70], "|", phone)