"""Pipeline: enrich -> score -> export (CSV for the dashboard, SQLite for later).

Input:  data/leads_filtered.json  (output of discovery, cleaning/dedupe, filtering)
Output: data/leads_final.csv, data/leads.db, data/leads_scored.json
"""
import argparse
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

from leadgen import enrichment, scoring

PLAIN = ["lead_id", "company_name", "category", "address", "phone", "phone_type", "email",
         "website", "maps_url", "rating", "review_count"]
TAIL = ["lead_score", "qualification", "qualification_reason", "source", "collected_at",
        "fetch_status"]
FIELDS = PLAIN + ["email_source", "social_links", "services"] + TAIL + ["data_provenance"]


def flatten(lead):
    prov = lead.get("data_provenance") or {}
    row = {k: lead.get(k) for k in PLAIN + TAIL}
    row["email_source"] = prov.get("email")
    row["social_links"] = "; ".join(f"{k}: {v}" for k, v in (lead.get("social_links") or {}).items())
    row["services"] = ", ".join(lead.get("services") or [])
    row["data_provenance"] = json.dumps(prov, ensure_ascii=False)
    return row


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def write_sqlite(rows, path):
    con = sqlite3.connect(path)
    con.execute("DROP TABLE IF EXISTS leads")
    cols = ", ".join(f'"{c}"' for c in FIELDS)
    con.execute(f"CREATE TABLE leads ({cols})")
    marks = ", ".join("?" for _ in FIELDS)
    con.executemany(f"INSERT INTO leads VALUES ({marks})",
                    [tuple(r[c] for c in FIELDS) for r in rows])
    con.commit()
    con.close()


def run(no_enrich=False):
    if not no_enrich:
        enrichment.run()
    scoring.run()
    leads = json.loads(Path("data/leads_scored.json").read_text(encoding="utf-8"))
    rows = [flatten(l) for l in sorted(leads, key=lambda x: -x["lead_score"])]
    write_csv(rows, "data/leads_final.csv")
    write_sqlite(rows, "data/leads.db")

    print("\n--- final dataset ---")
    print("leads:", len(rows))
    print("by label:", dict(Counter(r["qualification"] for r in rows)))
    print("with email:", sum(1 for r in rows if r["email"]))
    print("wrote data/leads_final.csv and data/leads.db")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Enrich, score and export leads.")
    ap.add_argument("--no-enrich", action="store_true", help="reuse data/leads_enriched.json")
    run(no_enrich=ap.parse_args().no_enrich)