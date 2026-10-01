# Mumbai Coworking Lead Engine

A small pipeline that discovers coworking-space leads in Mumbai, cleans and
deduplicates them, enriches them from each business's own website, scores them
with a transparent rubric, and serves them in a Streamlit dashboard.

Live dashboard: [FILL IN deployed link]

## Results on the real dataset

| Stage | Count |
|---|---|
| Raw records from 12 Mumbai areas | 353 |
| After deduplication | 247 (106 duplicates removed) |
| After removing non-coworking categories | 243 |
| Leads with a website | 217 |
| Websites fetched successfully | 180 |
| Leads with a trusted email | 109 |
| Leads with social links / services found | 103 / 133 |
| Hot / Warm / Cold / Incomplete | 60 / 104 / 55 / 24 |

All records are real listings. Nothing is synthetic.

## Architecture

```
SerpApi (Google Maps)  ->  discovery.py   raw records, cached to disk
                           cleaning.py    normalise + complete-linkage dedupe
                           filtering.py   drop non-coworking categories
                           enrichment.py  own-website scrape, per-field provenance
                           scoring.py     deterministic 0-100 rubric
                           pipeline.py    CSV + SQLite export
                           app.py         Streamlit dashboard
```

City and category are inputs to discovery; sources are meant to be pluggable.

## Data source and a caveat

Discovery uses SerpApi's Google Maps engine on its free plan, not Google's own
Places API (which needed a credit card I did not have). SerpApi is a third-party
service returning Google Maps data; this is a limitation and is stated here
openly. Responses are cached on disk, so re-runs cost no quota.
The raw data is committed, so you can reproduce everything after discovery
without an API key.

Enrichment visits only each business's own website. It respects robots.txt,
waits 1 second per host, uses an honest User-Agent and timeouts. Pages that
return 401/403/429 or show a CAPTCHA are skipped and recorded as `blocked`; they
are never bypassed. In this run: 15 blocked, 2 disallowed by robots.txt.
No logins, no scraping of social networks.

## Cleaning and deduplication

Fields are normalised (phones to +91 format, toll-free kept and labelled, URLs,
invisible unicode removed, SEO-stuffed names trimmed). Two records merge only if
a rule holds **and** the record matches every member of the group
(complete linkage, so A-B and B-C can never chain into A-C):

1. Same Google place_id.
2. Same direct phone, similar name, and overlapping building-specific address words.
3. Very similar name and strong address overlap.

Same website alone never merges (chains share one site across branches).
Different direct phones with different addresses never merge. A false merge
loses a real lead, whereas a leftover duplicate costs one row, so the rules lean
conservative. Real problems found and fixed on this data: invisible characters
in names, toll-free numbers wrongly rejected, area names inflating address
similarity, pincodes making different buildings look alike, and chaining of
different branches of The Executive Centre, WeWork, 603 and COWRKS.
Known edge case: UrbanWrk Tower A and Tower B (same phone) are merged as one operator.

## Enrichment: verified vs inferred

Every field carries its source in `data_provenance`:

- `google_maps_via_serpapi`: listing data
- `website_scraped`: read from the business's own site
- `website_scraped_related_domain`, `website_scraped_free_provider`: lower-confidence emails
- `rule_based`: computed by the scoring rubric

Nothing in this dataset is AI-inferred.

Email policy (a wrong email is worse than a missing one): an email is used only
if it is on the business's own domain, a closely related brand domain, or a free
provider. Emails are read only from `mailto:` links and visible text, never from
page code. This removed addresses belonging to web designers and font licences,
and package versions such as `leaflet@1.7.1` that looked like emails.

## Scoring (0-100, deterministic)

| Component | Max | Points |
|---|---|---|
| Contactability | 40 | direct mobile 15 / landline 12 / toll-free 6; email 15; website 10 |
| Online presence | 10 | 1 social profile 5, 2 or more 10 |
| Reputation | 20 | rating up to 10; review count up to 10 |
| Service fit | 30 | 5 per service found on the site, capped at 6 |

Hot is 80 or more, Warm 40-79, Cold below 40. Leads with no name, or with neither
phone nor email, are labelled Incomplete and capped at 39. The Hot threshold
was raised from 70 to 80 after the score histogram showed 38% of leads as Hot.
The score measures reachability and credibility, not buying intent.

### Evaluation against my own labels

I hand-labelled 20 random leads by judging them as a salesperson. First pass:
12/20 exact agreement (60%), 20/20 within one level. After I corrected a few
rows where I had misread ratings or review counts: 16/20 (80%). The 60% is the
independent figure. The remaining disagreements share a pattern: leads with a
reachable phone, a website and a decent rating but no email score just under the
Cold line, while a human would still call them. [FILL IN: threshold sweep result,
or delete this sentence.] [FILL IN: say honestly whether any of your labels were
copied from examples the assistant gave you.]

## AI usage

- The pipeline itself is rules-based by design. A fixed pipeline is cheaper,
  reproducible and auditable, and the scoring rubric can be explained line by line.
- [FILL IN if you add it: optional LLM-written reason that never changes the score,
  with a rules-only fallback when no API key is set.]
- AI assistants helped during development (design discussion, code, debugging).
  I made the decisions, and `DECISIONS.md` records them with the evidence.

## Limitations

- SerpApi is a third-party source and its free quota is limited.
- 24 of 243 leads are Incomplete: Google has no phone for them and they have no usable email.
- Regex enrichment misses JavaScript-only sites and contact forms; 19 sites errored and 26 have no website.
- Emails are not deliverability-verified, and a brand whose email domain looks unrelated to its site loses its email.
- A related-domain email is accepted on a brand-name match; this can be wrong.
- Deduplication can miss a duplicate or merge a same-phone neighbour (UrbanWrk).
- The score is a credibility proxy, not a prediction of who will buy.
- Ratings and review counts are a snapshot and change over time.
- Only business contact details from public listings are stored.

## How to run

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pytest

# optional: needs SERPAPI_KEY in .env and uses search quota
python -m leadgen.discovery --all

python -m leadgen.cleaning     # dedupe -> data/clean_leads.json
python -m leadgen.filtering    # -> data/leads_filtered.json
python -m leadgen.pipeline     # enrich + score + CSV/SQLite
streamlit run app.py
python -m pytest -q
```

Sample dataset: `data/leads_final.csv` (also `data/leads.db`).