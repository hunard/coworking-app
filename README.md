# Mumbai Coworking Lead Engine

A pipeline that discovers coworking-space leads in Mumbai from Google Maps data, cleans and deduplicates
them, enriches them from each business's own website, builds a quote-verified AI business profile for each,
scores them with a transparent rubric, and serves them in a Streamlit dashboard.

**Live dashboard:** https://coworking-app.streamlit.app/
**Sample dataset:** `data/leads_final.csv` (also `data/leads.db`, SQLite)

All records are real listings. Nothing in the dataset is synthetic.

## Contents
1. [Results](#results)
2. [Architecture](#architecture)
3. [Data source and compliance](#data-source-and-compliance)
4. [Cleaning and deduplication](#cleaning-and-deduplication)
5. [Enrichment: verified vs inferred](#enrichment-verified-vs-inferred)
6. [AI Business Profile](#ai-business-profile)
7. [Scoring](#scoring)
8. [Dashboard](#dashboard)
9. [Evaluation](#evaluation)
10. [Limitations](#limitations)
11. [How to run](#how-to-run)
12. [Project layout](#project-layout)

## Results

| Stage | Count |
|---|---|
| Raw records from 12 Mumbai areas | 353 |
| After deduplication | 247 (106 duplicates removed) |
| After removing non-coworking categories | 243 |
| Leads with a website | 217 |
| Websites fetched successfully (email/social/service scan) | 180 |
| Leads with a trusted email | 109 |
| Leads with social links / keyword services found | 103 / 133 |
| Leads with an AI Business Profile | 158 |
| Hot / Warm / Cold / Incomplete | 50 / 122 / 47 / 24 |

Average score is 56.5 (range 3 to 100). Hot is about 21% of leads.

## Architecture

```
SerpApi (Google Maps)  ->  discovery.py    raw records, responses cached on disk
                           cleaning.py     normalise + complete-linkage dedupe
                           filtering.py    drop non-coworking categories
                           enrichment.py   own-website scan: email, socials, keyword services, provenance
                           ai_enrich.py    LLM business profile; every claim needs a verified quote
                           scoring.py      deterministic 0-100 rubric (uses the verified profile)
                           pipeline.py     orchestration + CSV / SQLite export
                           areas.py        address -> Mumbai launch area
                           app.py          Streamlit dashboard
                           llm.py          swappable Gemini client with disk cache and retries
```

City and category are inputs to discovery. Sources are meant to be pluggable: a new source only has to return
the same record shape. Every external call (SerpApi, web pages, LLM) is cached on disk, so re-runs cost no quota.

## Data source and compliance

Discovery uses SerpApi's Google Maps engine on its free plan, not Google's own Places API (which needs a
credit card I did not have). SerpApi is a third-party service returning Google Maps data. This is a limitation and
is stated openly. The raw data is committed, so everything after discovery can be reproduced without an API key.

Website access (enrichment and AI profile) visits only each business's own website. It respects `robots.txt`,
waits at least 1 second per host, uses an honest User-Agent and timeouts, and skips pages that return
401/403/429 or show a CAPTCHA (recorded as `blocked`, never bypassed). In the enrichment run, 15 sites were
blocked and 2 were disallowed by robots.txt. There are no logins and no scraping of social networks.

Only business contact details from public listings are stored. No personal accounts or private data.

## Cleaning and deduplication

Fields are normalised: phones to +91 format (toll-free numbers kept and labelled `toll_free`), URLs, invisible
unicode removed, and SEO-stuffed listing names trimmed. Two records merge only if a rule holds **and** the record
matches every member of the group (complete linkage, so A-B and B-C can never chain into A-C):

1. Same Google `place_id`.
2. Same direct phone, similar name, and overlapping building-specific address words.
3. Very similar name and strong address overlap.

Never merged: records with the same website alone (chains share one site across branches), and records
with different direct phones and different addresses. A false merge loses a real lead, while a leftover duplicate
costs one row, so the rules lean conservative.

Real problems found and fixed on this data: invisible characters in names, toll-free numbers wrongly rejected,
area names inflating address similarity, pincodes making different buildings look identical, and chaining of
different branches of The Executive Centre, WeWork, 603 and COWRKS. `leadgen/audit.py` lists risky merges for review.
Known edge case: UrbanWrk Tower A and Tower B (same phone) are merged as one operator.

## Enrichment: verified vs inferred

Every field carries its origin in `data_provenance`:

| Provenance label | Meaning |
|---|---|
| `google_maps_via_serpapi` | Listing data (name, phone, address, rating, reviews) |
| `website_scraped` | Read from the business's own website |
| `website_scraped_related_domain`, `website_scraped_free_provider` | Lower-confidence emails |
| `ai_inferred_quote_verified` | Extracted by an LLM and kept only because its quote was found on the page |
| `rule_based` | Computed by the scoring rubric |
| `keyword_fallback` | Marketplace-fit points from keyword matching, used when no AI profile exists |

**Email policy** (a wrong email is worse than a missing one): an email is used only if it is on the business's own
domain, a closely related brand domain, or a free provider. Emails are read only from `mailto:` links and visible
text, never from page code. This removed addresses belonging to web designers and font licences, and package
versions such as `leaflet@1.7.1` that looked like emails.

## AI Business Profile

The score is rules-based on purpose: it is cheap, reproducible and explainable line by line. An LLM is used where
rules fail, which is understanding **what a business is and who it serves**. Keyword matching found services for
only 133 of 243 leads and cannot tell a single operator from a chain or a landlord.

For each complete lead with a readable website, the LLM (Gemini Flash-Lite, free tier, model set by
`GEMINI_MODEL`) reads the home page text and returns:

- `is_operator`: is this a flexible-workspace operator?
- `operator_type`: independent, chain branch, landlord/business centre, or unclear
- `space_types`: hot desk, day pass, private cabin, private office, meeting room, virtual office, and so on
- `target_customers`: freelancers, startups, SMEs, enterprises, students, agencies

**Guardrails**
- **Quote verification.** Every claim must carry an exact quote from the page. Code checks the quote is really in
  the page text and **drops the claim otherwise**. Values outside the allowed lists are also dropped.
- **The LLM never sets the score.** It supplies verified facts; the rules score them.
- **Doubt is flagged, not deleted.** A lead the AI judges "not an operator" gets `ai_flag` and zero marketplace-fit
  points, and stays in the dataset for human review.
- **Deterministic and cheap.** Temperature 0, responses cached in `data/llm_cache`, so the AI columns reproduce
  without an API key. Without a key the pipeline still runs and leads fall back to keyword fit.
- **Why not an autonomous agent?** A fixed pipeline is cheaper, reproducible and auditable. The model is used for
  one narrow extraction task with validated output.

AI step results: 158 leads profiled. Of the other 85: 24 incomplete (skipped), 17 no website, 30 page fetch
failed or blocked, 14 too little page text. `<<N claims checked, M dropped because the quote was not on the page>>`.

## Scoring

Deterministic, 0-100.

| Component | Max | Points |
|---|---|---|
| Contactability | 40 | direct mobile 15 / landline 12 / toll-free 6; email 15; website 10 |
| Online presence | 10 | 1 social profile 5, 2 or more 10 |
| Reputation | 20 | rating up to 10 (4.5+ = 10, 4.0+ = 7, 3.5+ = 4); reviews up to 10 (100+ = 10, 30+ = 7, 10+ = 4) |
| Marketplace fit | 30 | see below |

**Marketplace fit** answers: how useful is this space for a booking marketplace?
- Space types bookable by the hour or day (hot desk, day pass, meeting room, conference room, event space,
  training room): 4 points each, max 12. Other space types: 2 each, max 4.
- Operator type: independent 6 (quick local deal), chain branch 3 (head-office deal).
- Target customers: 2 each, max 6, plus 2 if small buyers (freelancers, startups, SMEs, students, agencies) are served.
- AI says "not an operator": 0. No AI profile: keyword fallback at 3 per service found on the site, max 18.
  No website data: 0.

Hot is 80 or more, Warm 40-79, Cold below 40. Leads with no name, or with neither phone nor email, are labelled
**Incomplete** and capped at 39. The Hot threshold was raised from 70 to 80 on the first rubric after its score
histogram showed 38% of leads as Hot; on the current rubric it yields about 21%.
The score measures reachability, credibility and fit for a booking marketplace, not buying intent.

**Rubric history.** v1 scored "service fit" from keyword counts. v2 (current) scores marketplace fit from the
quote-verified AI profile. Fit provenance across leads: 158 from the AI profile, 11 keyword fallback, 74 none.

## Dashboard

`streamlit run app.py`. Lead table with score, qualification, area, AI-profile and keyword filters, summary
counts, score distribution and CSV export of the current filter.
- **Where to launch first:** per-area counts of Hot, Warm, reachable and independent-operator leads, plus a
  "call first" list of the top 10 reachable leads in the current filter.
- **Lead detail:** the reason for the score, per-field provenance, and the exact website quotes behind each AI claim.

## Evaluation

**Scoring against my own labels.** I hand-labelled 20 random leads by judging them as a salesperson.
On rubric v1: 12/20 exact agreement (60%), 20/20 within one level. After I corrected a few rows where I had
misread ratings or review counts: 16/20 (80%). The 60% is the independent figure. The disagreements shared a pattern:
leads with a reachable phone, a website and a decent rating but no email scored just under the Cold line,
while a human would still call them.
`<<Rubric v2 re-check on the same 20 leads: X/20 exact, Y/20 within one level. State whether it improved.>>`
`<<Say honestly whether any labels were influenced by examples the assistant gave you.>>`

**AI profile accuracy (spot check).** I compared the profile of Star Coworking with its website text by hand:
all 7 returned space types were supported by the page, 2 of the 3 customer types were clearly named
(freelancers, enterprises) and "startups" was weakly supported. The operator type could not be verified from the
text. `<<Add 1-2 more sites you checked, with results.>>`

## Limitations

- SerpApi is a third-party source and its free quota is limited.
- 24 of 243 leads are Incomplete: Google has no phone for them and they have no usable email.
- 74 leads have no marketplace-fit data (no website, blocked page, too little text, or incomplete).
  Their scores rest on contactability and reputation only.
- Quote verification proves the quote is on the page, not that it supports the claim. "Independent" is the weakest
  field: the page title is often the only proof. Treat `independent` as a hint and `chain_branch` (usually backed
  by a list of cities) as stronger.
- The AI reads the home page only. Pricing, sub-pages and JavaScript-only sites are missed; regex enrichment also
  misses contact forms; 19 sites errored and 26 have no website.
- Emails are not deliverability-verified, and a brand whose email domain looks unrelated to its site loses its email.
  A related-domain email is accepted on a brand-name match, which can be wrong.
- Deduplication can miss a duplicate or merge a same-phone neighbour (UrbanWrk).
- Marketplace-fit weights are hand-set judgements, not learned. The score does not predict who will buy.
- Free-tier Gemini prompts may be used by Google to improve its products. Only public website text is sent.
  Model names get retired (the first model I used returned 404), so the model is configurable via `GEMINI_MODEL`.
- Ratings and review counts are a snapshot and change over time.

## How to run

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` (never commit it):
```
SERPAPI_KEY=...          # only needed for discovery
GEMINI_API_KEY=...       # only needed for new AI profiles
GEMINI_MODEL=gemini-3.5-flash-lite
```

Reproduce from the committed data, with no keys needed (AI answers come from `data/llm_cache`):
```bash
python -m leadgen.cleaning      # dedupe            -> data/clean_leads.json
python -m leadgen.filtering     # category filter   -> data/leads_filtered.json
python -m leadgen.pipeline      # enrich + AI profile + score + CSV/SQLite
streamlit run app.py
python -m pytest -q
```

Full run from scratch (uses search quota):
```bash
python -m leadgen.discovery --all    # 12 areas, up to 2 pages each
```
- `python -m leadgen.discovery` with no flags searches only Andheri with 1 page, to protect your quota.
- A non-default city or category writes to its own file (for example `data/raw_pune_coworking_space.json`)
  and never overwrites the Mumbai data.
- A city with no area list gets one city-wide query. Multi-area coverage needs one entry in `CITY_AREAS`.
- Pipeline flags: `--no-enrich` reuses enrichment output, `--no-ai` skips the AI step.

## Project layout

```
leadgen/   discovery, cleaning, filtering, enrichment, ai_enrich, scoring, pipeline, areas, llm, audit
tests/     pytest suite: cleaning, dedupe, enrichment, scoring, AI quote validation
data/      raw_leads.json, leads_final.csv, leads.db, llm_cache/
app.py     Streamlit dashboard
DECISIONS.md   design decisions and the evidence behind them
```

AI assistants helped during development (design discussion, code, debugging). I made the design decisions and
checked them against real data, and `DECISIONS.md` records them with the evidence.