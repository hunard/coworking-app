import json

import pandas as pd
import streamlit as st

from leadgen.areas import area_of

DATA = "data/leads_final.csv"
LABELS = ["Hot", "Warm", "Cold", "Incomplete"]
AI_COLS = ["ai_is_operator", "ai_operator_type", "ai_space_types", "ai_target_customers",
           "ai_flag", "ai_status", "ai_evidence"]

st.set_page_config(page_title="Mumbai Coworking Leads", layout="wide")


@st.cache_data
def load():
    df = pd.read_csv(DATA, dtype=str, encoding="utf-8-sig").fillna("")
    for c in AI_COLS:                      # works even if the AI step has not been run yet
        if c not in df.columns:
            df[c] = ""
    df["lead_score"] = pd.to_numeric(df["lead_score"], errors="coerce").fillna(0).astype(int)
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df["review_count"] = pd.to_numeric(df["review_count"], errors="coerce")
    df["area"] = df["address"].map(area_of)
    return df


def options(series):
    return sorted({s.strip() for v in series for s in v.split(",") if s.strip()})


df = load()

st.title("Mumbai Coworking Leads")
st.caption("Real listings from Google Maps data (via SerpApi), enriched from each business's own "
           "website. The score is rules-based: contactability, online presence, reputation, and "
           "fit for a booking marketplace. The marketplace-fit points use an AI Business Profile "
           "(operator type, space types, customers) in which every claim is kept only if its quote "
           "was found on the website. The AI never sets the score itself.")

# ---------- sidebar filters ----------
st.sidebar.header("Filters")
labels = st.sidebar.multiselect("Qualification", LABELS, default=LABELS)
lo, hi = st.sidebar.slider("Lead score", 0, 100, (0, 100))
areas = st.sidebar.multiselect("Area", sorted(df["area"].unique()))
query = st.sidebar.text_input("Search name or address")
only_email = st.sidebar.checkbox("Has email")
only_direct = st.sidebar.checkbox("Has direct phone (not toll-free)")
wanted = st.sidebar.multiselect("Must offer (keywords found on website)", options(df["services"]))

st.sidebar.header("AI Business Profile (quote-verified)")
op_types = st.sidebar.multiselect("Operator type", options(df["ai_operator_type"]))
ai_spaces = st.sidebar.multiselect("Space types", options(df["ai_space_types"]))
ai_customers = st.sidebar.multiselect("Target customers", options(df["ai_target_customers"]))
hide_flagged = st.sidebar.checkbox("Hide leads the AI flagged as not an operator")

view = df[df["qualification"].isin(labels) & df["lead_score"].between(lo, hi)]
if areas:
    view = view[view["area"].isin(areas)]
if query:
    view = view[view["company_name"].str.contains(query, case=False, regex=False)
                | view["address"].str.contains(query, case=False, regex=False)]
if only_email:
    view = view[view["email"] != ""]
if only_direct:
    view = view[view["phone_type"].isin(["mobile", "landline"])]
for s in wanted:
    view = view[view["services"].str.contains(s, regex=False)]
if op_types:
    view = view[view["ai_operator_type"].isin(op_types)]
for s in ai_spaces:
    view = view[view["ai_space_types"].str.contains(s, regex=False)]
for s in ai_customers:
    view = view[view["ai_target_customers"].str.contains(s, regex=False)]
if hide_flagged:
    view = view[view["ai_flag"] == ""]

# ---------- summary counts ----------
cols = st.columns(7)
cols[0].metric("Showing", f"{len(view)} / {len(df)}")
for col, label in zip(cols[1:5], LABELS):
    col.metric(label, int((view["qualification"] == label).sum()))
cols[5].metric("With email", int((view["email"] != "").sum()))
cols[6].metric("AI-profiled", int((view["ai_status"] == "ok").sum()))

# ---------- where to launch first ----------
st.subheader("Where to launch first")
st.caption("Based on the leads currently shown (Incomplete leads excluded). 'Reachable' means a direct "
           "phone or an email. 'Independent' means the AI profile found a single-brand operator.")
ok = view[view["qualification"] != "Incomplete"].copy()
if ok.empty:
    st.info("No leads to summarise with the current filters.")
else:
    ok["reachable"] = ok["phone_type"].isin(["mobile", "landline"]) | (ok["email"] != "")
    ok["independent"] = ok["ai_operator_type"] == "independent"
    by_area = ok.groupby("area").agg(
        leads=("company_name", "count"),
        hot=("qualification", lambda s: int((s == "Hot").sum())),
        warm=("qualification", lambda s: int((s == "Warm").sum())),
        reachable=("reachable", "sum"),
        independent=("independent", "sum"),
        avg_score=("lead_score", "mean"),
    ).reset_index()
    by_area["avg_score"] = by_area["avg_score"].round(0).astype(int)
    by_area = by_area.sort_values(["hot", "reachable", "avg_score"], ascending=False)
    left, right = st.columns([3, 2])
    left.dataframe(by_area, hide_index=True, width="stretch")
    right.bar_chart(by_area.set_index("area")["hot"])

    st.markdown("**Call first: top 10 reachable leads in the current filter**")
    call = ok[ok["reachable"]].sort_values(["lead_score", "review_count"], ascending=False).head(10)
    st.dataframe(
        call[["company_name", "area", "lead_score", "qualification", "phone", "email",
              "ai_operator_type", "website"]],
        hide_index=True, width="stretch",
        column_config={"website": st.column_config.LinkColumn("Website")},
    )

with st.expander("Score distribution"):
    st.bar_chart(view["lead_score"].floordiv(10).mul(10).value_counts().sort_index())

# ---------- lead table ----------
st.subheader("All leads")
table_cols = ["company_name", "area", "lead_score", "qualification", "phone", "phone_type", "email",
              "website", "rating", "review_count", "services", "ai_operator_type",
              "ai_target_customers", "ai_space_types", "address", "maps_url"]
st.dataframe(
    view[table_cols],
    hide_index=True,
    width="stretch",
    column_config={
        "lead_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
        "website": st.column_config.LinkColumn("Website"),
        "maps_url": st.column_config.LinkColumn("Maps", display_text="open"),
        "ai_operator_type": "AI: operator type",
        "ai_target_customers": "AI: customers",
        "ai_space_types": "AI: space types",
    },
)

st.download_button(
    "Download filtered leads (CSV)",
    view.to_csv(index=False).encode("utf-8-sig"),
    file_name="coworking_leads_filtered.csv",
    mime="text/csv",
)

# ---------- single lead detail ----------
st.subheader("Lead detail")
if view.empty:
    st.info("No leads match the filters.")
else:
    pick = st.selectbox(
        "Choose a lead",
        view.index,
        format_func=lambda i: f"{view.loc[i, 'company_name']}  (score {view.loc[i, 'lead_score']})",
    )
    row = view.loc[pick]
    prov = json.loads(row["data_provenance"] or "{}")
    st.markdown(f"**{row['company_name']}**: {row['qualification']}, score {row['lead_score']}/100, area {row['area']}")
    st.write("**Why this score:**", row["qualification_reason"])

    detail = []
    for field in ["phone", "email", "website", "rating", "review_count",
                  "social_links", "services", "lead_score"]:
        detail.append({"field": field, "value": str(row[field]), "source": prov.get(field, "")})
    for field, key in [("ai_operator_type", "operator_type"), ("ai_space_types", "space_types"),
                       ("ai_target_customers", "target_customers")]:
        if row[field]:
            detail.append({"field": field, "value": str(row[field]), "source": prov.get(key, "")})
    st.table(pd.DataFrame(detail))

    st.markdown("**Proof from the website (exact quotes the AI used):**")
    evidence = json.loads(row["ai_evidence"] or "{}")
    if row["ai_status"] == "ok" and evidence:
        st.table(pd.DataFrame([{"claim": k, "quote from website": v} for k, v in evidence.items()]))
        if row["ai_flag"]:
            st.warning("The AI judged this is probably not a coworking operator. Review manually.")
    else:
        st.caption(f"No AI profile for this lead (status: {row['ai_status'] or 'not run'}).")

    st.caption("Sources: google_maps_via_serpapi = listing data; website_scraped = read from the "
               "business's own site; rule_based = computed by the scoring rubric; "
               "ai_inferred_quote_verified = extracted by an LLM and kept only because its quote "
               "was found on the page.")