"""Healthcare Denial Management Dashboard: an educational Streamlit sandbox.

Run with:  streamlit run app.py

Everything runs in memory. The mock claims are generated on first load (seeded, so
they are reproducible) and every number on the page is computed from whatever the
sidebar filters leave in view. See denial_dashboard/__init__.py for the module map.
"""
from __future__ import annotations

import inspect

import pandas as pd
import streamlit as st

from denial_dashboard import charts, data, logic, sql_lab, sql_lab_ui, training

# ---------------------------------------------------------------- page setup
st.set_page_config(page_title="Denial Management Dashboard", layout="wide", initial_sidebar_state="expanded")

def _wide_kwargs(fn) -> dict:
    """Newer Streamlit takes width="stretch"; older takes use_container_width=True. Ask the function."""
    params = inspect.signature(fn).parameters
    return {"width": "stretch"} if "width" in params else {"use_container_width": True}


_WIDE_CHART = _wide_kwargs(st.plotly_chart)
_WIDE_TABLE = _wide_kwargs(st.dataframe)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.75rem; padding-bottom: 2rem; }
      h1 { letter-spacing: -0.01em; font-weight: 650; }
      [data-testid="stMarkdownContainer"] h3 { font-size: 1.05rem; font-weight: 600; padding-top: 0.2rem; padding-bottom: 0.1rem; }
      [data-testid="stMetricValue"] { font-size: 2.1rem; font-weight: 600; letter-spacing: -0.02em; }
      [data-testid="stMetricLabel"] p { color: #52606d; font-size: 0.9rem; }
      [data-testid="stMetricDelta"] { font-size: 0.85rem; }
      .card-caption { color: #52606d; font-size: 0.85rem; margin-top: -0.35rem; margin-bottom: 0.25rem; }
      .insight-title { font-weight: 600; font-size: 1rem; margin-bottom: 0.35rem; }
      .insight-label { color: #52606d; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 0.6rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_claims(seed: int, n: int) -> pd.DataFrame:
    """Generate and enrich the mock claims once per (seed, n); Streamlit caches the result."""
    return logic.enrich_claims(data.generate_claims(n=n, seed=seed))


def get_practice_db(seed: int, n: int):
    """The SQL Lab's in-memory SQLite database, one per browser session.

    Kept in session_state rather than a shared cache so that, on a hosted app with several learners
    at once, no two sessions ever share one SQLite connection. Rebuilding takes well under a second.
    """
    key = (seed, n)
    if st.session_state.get("_sql_db_key") != key:
        st.session_state["_sql_db"] = sql_lab.build_database(load_claims(seed, n))
        st.session_state["_sql_db_key"] = key
    return st.session_state["_sql_db"]


def show_chart(fig) -> None:
    st.plotly_chart(fig, config=charts.PLOTLY_CONFIG, **_WIDE_CHART)


def show_table(df: pd.DataFrame, **kwargs) -> None:
    st.dataframe(df, hide_index=kwargs.pop("hide_index", True), **_WIDE_TABLE, **kwargs)


def md_safe(text: str) -> str:
    """Streamlit markdown reads $...$ as LaTeX; escape dollar signs in prose that mentions money."""
    return text.replace("$", "\\$")


def signed(v: float, suffix: str = "", money: bool = False) -> str:
    if money:
        return ("+" if v >= 0 else "-") + "${:,.0f}".format(abs(v))
    return ("+" if v >= 0 else "") + "{:.1f}{}".format(v, suffix)


# ---------------------------------------------------------------- sidebar: filters
with st.sidebar:
    st.markdown("### Filters")
    st.caption("Every number on the page recalculates from the claims left in view.")
    accounts = st.multiselect("Account", data.ACCOUNTS, default=data.ACCOUNTS)
    payers = st.multiselect("Payer", data.PAYERS, default=data.PAYERS)

    st.markdown("---")
    with st.expander("Mock data controls"):
        seed = int(st.number_input("Random seed", min_value=1, max_value=99999, value=42, step=1,
                                   help="Same seed, same claims. Change it to see which findings are structural and which are noise."))
        n_claims = int(st.select_slider("Number of claims", options=[1000, 2500, 5000, 10000], value=5000))
    st.caption("All claims, payers, accounts and dollar amounts are synthetic. No real patient or client data is used.")

df_all = load_claims(seed, n_claims)
df = df_all[df_all["Account_Name"].isin(accounts) & df_all["Payer"].isin(payers)]
start, end = data.period_bounds(df_all)

# ---------------------------------------------------------------- header
st.title("Healthcare Denial Management Dashboard")
st.caption(
    "Claims submitted {s} to {e} · {n:,} of {t:,} claims in view · "
    "Denial rate = denied ÷ all claims · Clean claim rate = paid on first submission ÷ all claims".format(
        s=start.strftime("%d %b %Y"), e=end.strftime("%d %b %Y"), n=len(df), t=len(df_all))
)

if df.empty:
    st.warning("No claims match the current filters. Pick at least one account and one payer in the sidebar.")
    st.stop()

tab_dash, tab_learn, tab_sql = st.tabs(["Dashboard", "Ritu's Analyst Training Companion", "SQL Lab"])

# ================================================================ DASHBOARD
with tab_dash:
    k = logic.compute_kpis(df)
    d = k["delta"]

    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.metric("Total revenue at risk", "${:,.0f}".format(k["revenue_at_risk"]),
                      delta=signed(d["at_risk_change"], money=True) + " " + d["label"] if d else None,
                      delta_color="inverse",
                      help="Billed dollars on denied claims in view. Up is bad.")
            st.markdown('<div class="card-caption">{:,} denied claims · {:.1f}% of ${:,.0f} billed</div>'.format(
                k["denied_claims"], 100.0 * k["revenue_at_risk"] / k["billed_total"] if k["billed_total"] else 0, k["billed_total"]),
                unsafe_allow_html=True)
    with c2:
        with st.container(border=True):
            st.metric("Overall denial rate", "{:.1f}%".format(k["denial_rate"]),
                      delta=signed(d["denial_rate_pts"], " pts") + " " + d["label"] if d else None,
                      delta_color="inverse",
                      help="Denied ÷ all claims in view. Up is bad.")
            st.markdown('<div class="card-caption">{:,} denied of {:,} claims</div>'.format(
                k["denied_claims"], k["total_claims"]), unsafe_allow_html=True)
    with c3:
        with st.container(border=True):
            st.metric("Clean claim rate", "{:.1f}%".format(k["clean_claim_rate"]),
                      delta=signed(d["clean_rate_pts"], " pts") + " " + d["label"] if d else None,
                      help="Paid on the first submission ÷ all claims in view. Up is good.")
            st.markdown('<div class="card-caption">{:,} paid first time · {:,} paid after rework</div>'.format(
                k["clean_claims"], k["paid_claims"] - k["clean_claims"]), unsafe_allow_html=True)

    st.write("")
    left, right = st.columns([3, 2])
    with left:
        with st.container(border=True):
            st.markdown("### Payer wall of shame")
            st.markdown('<div class="card-caption">Denial rate by payer, worst first. Hairline marks the rate across every claim in view.</div>',
                        unsafe_allow_html=True)
            show_chart(charts.payer_wall_of_shame(logic.rate_by(df, "Payer"), k["denial_rate"]))
    with right:
        with st.container(border=True):
            st.markdown("### Root cause of denials")
            st.markdown('<div class="card-caption">Share of denied claims by business bucket. Hover for dollars.</div>',
                        unsafe_allow_html=True)
            summary = logic.root_cause_summary(df)
            if summary.empty:
                st.info("No denials in view.")
            else:
                show_chart(charts.root_cause_donut(summary))

    with st.container(border=True):
        head, ctrl = st.columns([3, 2])
        with head:
            st.markdown("### Denial rate trend")
            st.markdown('<div class="card-caption">By claim submission month, over the six months in the data.</div>',
                        unsafe_allow_html=True)
        with ctrl:
            view = st.radio("Trend view", ["Overall denial rate", "By root cause"], horizontal=True,
                            label_visibility="collapsed")
        if view == "Overall denial rate":
            show_chart(charts.denial_trend(logic.monthly_trend(df)))
        else:
            show_chart(charts.denial_trend_by_category(logic.monthly_trend_by_category(df)))
            st.caption("Each line is that bucket's share of all claims submitted that month, so the three lines add up to the overall rate.")

    t_left, t_right = st.columns([3, 2])
    with t_left:
        with st.container(border=True):
            st.markdown("### Denied claims by payer and root cause")
            st.markdown('<div class="card-caption">The table behind the charts above. Counts of denied claims; dollars are billed amounts on those claims.</div>',
                        unsafe_allow_html=True)
            pivot = logic.payer_by_category(df)
            if pivot.empty:
                st.info("No denials in view.")
            else:
                show_table(pivot, hide_index=False,
                           column_config={"Revenue at risk": st.column_config.NumberColumn(format="dollar")})
    with t_right:
        with st.container(border=True):
            st.markdown("### Root cause, counts and dollars")
            st.markdown('<div class="card-caption">Same buckets as the ring chart, with the dollars that the ring cannot show.</div>',
                        unsafe_allow_html=True)
            summary = logic.root_cause_summary(df)
            if not summary.empty:
                show_table(summary[["short", "denied_claims", "share_of_denials_pct", "revenue_at_risk", "share_of_dollars_pct"]]
                           .rename(columns={"short": "Root cause", "denied_claims": "Denied", "share_of_denials_pct": "% of denials",
                                            "revenue_at_risk": "Revenue at risk", "share_of_dollars_pct": "% of dollars"}),
                           column_config={"% of denials": st.column_config.NumberColumn(format="%.1f%%"),
                                          "% of dollars": st.column_config.NumberColumn(format="%.1f%%"),
                                          "Revenue at risk": st.column_config.NumberColumn(format="dollar")})

    with st.expander("Denied claims in view (detail and download)"):
        den = df[df["Is_Denied"]][["Claim_ID", "Account_Name", "Payer", "Claim_Submission_Date", "Billed_Amount",
                                   "Denial_Reason_Code", "Denial_Code_Clean", "Root_Cause_Short", "Denial_Reason_Description"]]
        den = den.rename(columns={"Denial_Reason_Code": "Raw code (as received)", "Denial_Code_Clean": "Normalized code",
                                  "Root_Cause_Short": "Root cause"})
        den = den.assign(Claim_Submission_Date=pd.to_datetime(den["Claim_Submission_Date"]).dt.date)
        st.caption("{:,} denied claims. The raw code column shows the formatting mess the mapping function repairs.".format(len(den)))
        show_table(den.sort_values("Billed_Amount", ascending=False),
                   column_config={"Billed_Amount": st.column_config.NumberColumn(format="dollar")})
        st.download_button("Download denied claims (CSV)", den.to_csv(index=False).encode("utf-8"),
                           file_name="denied_claims_in_view.csv", mime="text/csv")

# ================================================================ TRAINING COMPANION
with tab_learn:
    st.markdown("## Ritu's Analyst Training Companion")
    st.caption("How an analyst reads this dashboard, why your coding background is the hard part already done, "
               "and the SQL behind the numbers. The examples below use the claims currently in view.")

    st.markdown("### 1. The business problem this dashboard solves")
    st.markdown(training.BUSINESS_PROBLEM_MD)

    st.markdown("### 2. How your domain experience mapped the raw data")
    st.markdown(training.DOMAIN_MAPPING_MD)
    show_table(logic.code_table())

    st.markdown("### 3. Three example insights, read from the data in view")
    st.caption("Change the filters and come back: the wording updates because the numbers do.")
    for ins in training.generate_insights(df):
        with st.container(border=True):
            st.markdown('<div class="insight-title">{}</div>'.format(ins["title"]), unsafe_allow_html=True)
            st.markdown('<div class="insight-label">What the data shows</div>', unsafe_allow_html=True)
            st.markdown(md_safe(ins["finding"]))
            st.markdown('<div class="insight-label">Why it matters</div>', unsafe_allow_html=True)
            st.markdown(md_safe(ins["so_what"]))
            st.markdown('<div class="insight-label">Action item</div>', unsafe_allow_html=True)
            st.markdown(md_safe(ins["action"]))

    st.markdown("### 4. The SQL an analyst writes behind the scenes")
    st.markdown("**Question:** which five payers deny the highest share of our claims, and how much money is that?")
    sql_text = logic.sql_top_payers_text(start, end)
    st.code(sql_text, language="sql")
    st.markdown("**Result, run live against the claims in view:**")
    show_table(logic.run_sql_top_payers(df, start, end),
               column_config={"denial_rate_pct": st.column_config.NumberColumn("denial_rate_pct", format="%.1f"),
                              "revenue_at_risk": st.column_config.NumberColumn("revenue_at_risk", format="dollar")})
    st.markdown(training.SQL_WALKTHROUGH_MD)
    st.markdown("**The same logic in pandas** (this is what `logic.top_denying_payers()` does):")
    st.code(training.PANDAS_TOP_PAYERS, language="python")

    st.markdown("### 5. How to study this app")
    st.markdown(training.HOW_TO_STUDY_MD)

# ================================================================ SQL LAB
with tab_sql:
    sql_lab_ui.render(get_practice_db(seed, n_claims), show_table)
