"""Compare my hand labels with the rule-based labels and print agreement."""
import csv
import json
from collections import Counter
from pathlib import Path

ORDER = ["Cold", "Warm", "Hot"]


def run(labels="data/hand_labels.csv", scored="data/leads_scored.json"):
    model = {l["lead_id"]: l for l in json.loads(Path(scored).read_text(encoding="utf-8"))}
    rows = list(csv.DictReader(open(labels, encoding="utf-8")))
    rows = [r for r in rows if r["my_label"].strip()]
    if not rows:
        print("No labels found: fill the my_label column first.")
        return

    agree = 0
    near = 0
    confusion = Counter()
    misses = []
    for r in rows:
        mine = r["my_label"].strip().capitalize()
        lead = model[r["lead_id"]]
        theirs = lead["qualification"]
        confusion[(mine, theirs)] += 1
        if mine == theirs:
            agree += 1
            near += 1
        else:
            if mine in ORDER and theirs in ORDER and abs(ORDER.index(mine) - ORDER.index(theirs)) == 1:
                near += 1
            misses.append((r["company_name"], mine, theirs, lead["lead_score"], lead["qualification_reason"]))

    n = len(rows)
    print(f"labelled leads: {n}")
    print(f"exact agreement: {agree}/{n} = {agree / n:.0%}")
    print(f"within one level: {near}/{n} = {near / n:.0%}")
    print("\n(my label, model label): count")
    for k, v in sorted(confusion.items()):
        print(" ", k, v)
    print("\nDisagreements:")
    for name, mine, theirs, score, reason in misses:
        print(f"- {name}: I said {mine}, model said {theirs} ({score})")
        print(f"    {reason}")


if __name__ == "__main__":
    run()