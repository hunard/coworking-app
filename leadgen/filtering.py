"""Drop businesses that are clearly not coworking / flexible-office providers."""
import json

DENY = {"Student dormitory", "Software company", "Contractor", "Business park"}
REVIEW = {"Corporate office"}   # may be a WeWork HQ or a random company: check by eye

if __name__ == "__main__":
    leads = json.load(open("data/clean_leads.json", encoding="utf-8"))
    kept = [l for l in leads if l.get("category") not in DENY]
    print(f"kept {len(kept)} of {len(leads)}")
    print("\nRemoved:")
    for l in leads:
        if l.get("category") in DENY:
            print(f"  [{l['category']}] {l['company_name']}")
    print("\nPlease review these (kept for now):")
    for l in kept:
        if l.get("category") in REVIEW:
            print(f"  {l['company_name']} | {l.get('website')}")
    json.dump(kept, open("data/leads_filtered.json", "w", encoding="utf-8"), indent=1)