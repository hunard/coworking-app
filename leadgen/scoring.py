"""Deterministic lead scoring (0-100). No LLM decides the score.

Score = contactability (40) + online presence (10) + reputation (20) + service fit (30).
Incomplete leads (no name, or no phone AND no email) are capped at 39.
The score measures lead quality and reachability, not buying intent.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

INCOMPLETE_CAP = 39
HOT_MIN = 70
WARM_MIN = 40


def is_complete(lead):
    return bool(lead.get("company_name")) and bool(lead.get("phone") or lead.get("email"))


def score_lead(lead):
    """Return (score, label, reason, breakdown)."""
    parts = []  # (component, points, evidence text)

    # 1. Contactability (max 40)
    ptype = lead.get("phone_type")
    if lead.get("phone"):
        if ptype == "toll_free":
            parts.append(("contact", 6, "toll-free phone only"))
        elif ptype == "landline":
            parts.append(("contact", 12, "direct landline"))
        else:
            parts.append(("contact", 15, "direct mobile phone"))
    else:
        parts.append(("contact", 0, "no phone"))

    if lead.get("email"):
        parts.append(("contact", 15, "email found on official website"))
    else:
        parts.append(("contact", 0, "no email"))

    if lead.get("website"):
        parts.append(("contact", 10, "has website"))
    else:
        parts.append(("contact", 0, "no website"))

    # 2. Online presence (max 10)
    n_social = len(lead.get("social_links") or {})
    if n_social >= 2:
        parts.append(("presence", 10, f"{n_social} social profiles"))
    elif n_social == 1:
        parts.append(("presence", 5, "1 social profile"))

    # 3. Reputation (max 20)
    rating = lead.get("rating")
    if rating:
        if rating >= 4.5:
            pts = 10
        elif rating >= 4.0:
            pts = 7
        elif rating >= 3.5:
            pts = 4
        else:
            pts = 1
        parts.append(("reputation", pts, f"rating {rating}"))

    reviews = lead.get("review_count") or 0
    if reviews >= 100:
        pts = 10
    elif reviews >= 30:
        pts = 7
    elif reviews >= 10:
        pts = 4
    elif reviews >= 1:
        pts = 2
    else:
        pts = 0
    if pts:
        parts.append(("reputation", pts, f"{reviews} reviews"))

    # 4. Service fit (max 30)
    services = lead.get("services") or []
    if services:
        pts = min(len(services), 6) * 5
        parts.append(("services", pts, f"{len(services)} services listed on site"))

    breakdown = {}
    for comp, pts, _ in parts:
        breakdown[comp] = breakdown.get(comp, 0) + pts
    score = min(100, sum(breakdown.values()))

    complete = is_complete(lead)
    if not complete:
        score = min(score, INCOMPLETE_CAP)
        label = "Incomplete"
    elif score >= HOT_MIN:
        label = "Hot"
    elif score >= WARM_MIN:
        label = "Warm"
    else:
        label = "Cold"

    positives = [text for _, pts, text in parts if pts > 0]
    gaps = [text for _, pts, text in parts if pts == 0]
    reason = "; ".join(positives)
    if gaps:
        reason += " | gaps: " + ", ".join(gaps)
    if not complete:
        reason += " | capped at 39: no direct contact (phone or email)"
    return score, label, reason, breakdown


def score_all(leads):
    out = []
    for lead in leads:
        score, label, reason, breakdown = score_lead(lead)
        row = dict(lead)
        row.update(lead_score=score, qualification=label,
                   qualification_reason=reason, score_breakdown=breakdown)
        prov = dict(row.get("data_provenance") or {})
        prov["lead_score"] = "rule_based"
        row["data_provenance"] = prov
        out.append(row)
    return out


def run(src="data/leads_enriched.json", dst="data/leads_scored.json"):
    leads = json.loads(Path(src).read_text(encoding="utf-8"))
    scored = score_all(leads)
    Path(dst).write_text(json.dumps(scored, indent=2, ensure_ascii=False), encoding="utf-8")
    print("labels:", dict(Counter(l["qualification"] for l in scored)))
    scores = [l["lead_score"] for l in scored]
    print("score min/avg/max:", min(scores), round(sum(scores) / len(scores), 1), max(scores))
    print("\nTop 5:")
    for l in sorted(scored, key=lambda x: -x["lead_score"])[:5]:
        print(f"  {l['lead_score']:>3} {l['qualification']:<10} {l['company_name']}")
    print("\nBottom 5:")
    for l in sorted(scored, key=lambda x: x["lead_score"])[:5]:
        print(f"  {l['lead_score']:>3} {l['qualification']:<10} {l['company_name']}")
    print("wrote", dst)


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    run()