
import json

import pandas as pd
import streamlit as st

DATA = "data/leads_final.csv"
LABELS = ["Hot", "Warm", "Cold", "Incomplete"]

st.set_page_config(page_title="Mumbai Coworking Leads", layout="wide")


@st.cache_data
def load():
    df = pd.read_csv(DATA, dtype=str, encoding="utf-8-sig").fillna("")
    df["lead_score"] = pd.to_numeric(df["lead_score"], errors="coerce").fillna(0).astype(int)
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    df["review_count"] = pd.to_numeric(df["review_count"], errors="coerce")
    return df


df = load()

st.title("Mumbai Coworking Leads")
st.caption("Real listings from Google Maps data (via SerpApi), enriched from each business's own "
           "website and scored with a deterministic rubric. The score measures reachability and "
           "credibility, not buying intent.")

# ---------- sidebar filters ----------
st.sidebar.header("Filters")
labels = st.sidebar.multiselect("Qualification", LABELS, default=LABELS)
lo, hi = st.sidebar.slider("Lead score", 0, 100, (0, 100))
query = st.sidebar.text_input("Search name or address")
only_email = st.sidebar.checkbox("Has email")
only_direct = st.sidebar.checkbox("Has direct phone (not toll-free)")
all_services = sorted({s.strip() for v in df["services"] for s in v.split(",") if s.strip()})
wanted = st.sidebar.multiselect("Must offer (found on website)", all_services)

view = df[df["qualification"].isin(labels) & df["lead_score"].between(lo, hi)]
if query:
    view = view[view["company_name"].str.contains(query, case=False, regex=False)
                | view["address"].str.contains(query, case=False, regex=False)]
if only_email:
    view = view[view["email"] != ""]
if only_direct:
    view = view[view["phone_type"].isin(["mobile", "landline"])]
for s in wanted:
    view = view[view["services"].str.contains(s, regex=False)]

# ---------- summary counts ----------
cols = st.columns(6)
cols[0].metric("Showing", f"{len(view)} / {len(df)}")
for col, label in zip(cols[1:5], LABELS):
    col.metric(label, int((view["qualification"] == label).sum()))
cols[5].metric("With email", int((view["email"] != "").sum()))

with st.expander("Score distribution"):
    st.bar_chart(view["lead_score"].floordiv(10).mul(10).value_counts().sort_index())

# ---------- lead table ----------
table_cols = ["company_name", "lead_score", "qualification", "phone", "phone_type", "email",
              "website", "rating", "review_count", "services", "address", "maps_url"]
st.dataframe(
    view[table_cols],
    hide_index=True,
    width="stretch",
    column_config={
        "lead_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
        "website": st.column_config.LinkColumn("Website"),
        "maps_url": st.column_config.LinkColumn("Maps", display_text="open"),
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
    st.markdown(f"**{row['company_name']}**: {row['qualification']}, score {row['lead_score']}/100")
    st.write("**Why this score:**", row["qualification_reason"])

    detail = []
    for field in ["phone", "email", "website", "rating", "review_count",
                  "social_links", "services", "lead_score"]:
        detail.append({"field": field, "value": str(row[field]), "source": prov.get(field, "")})
    st.table(pd.DataFrame(detail))
    st.caption("Sources: google_maps_via_serpapi = listing data; website_scraped = read from the "
               "business's own site; rule_based = computed by the scoring rubric. No value in this "
               "dataset is AI-inferred.")
