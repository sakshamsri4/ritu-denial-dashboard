"""Ritu's Analyst Training Companion: the narrative layer.

Static explanations live here as Markdown strings. The three "example insights"
are generated from whatever data is currently filtered, so the companion always
talks about the numbers on screen rather than a canned example.
"""
from __future__ import annotations

import pandas as pd

from .logic import (CATEGORIES, CATEGORY_ACTION, CATEGORY_CODING, CATEGORY_ELIGIBILITY,
                    CATEGORY_OPERATIONS, CATEGORY_OWNER, CATEGORY_SHORT, rate_by, root_cause_summary)

BUSINESS_PROBLEM_MD = """
**The problem in one sentence:** a hospital or physician group bills millions of dollars a
month, and somewhere between 5% and 20% of those claims come back denied. Every denied claim
is cash that has stopped moving, staff time to rework it, and a real chance the money is never
collected at all.

**What executives need from this dashboard**

- **How much money is stuck, right now?** That is *Total Revenue at Risk*. A CFO reads it as
  working capital they cannot spend yet.
- **Is the problem getting better or worse?** The *Denial Rate* and its month-over-month
  change answer that in one glance. Industry benchmarks put a healthy first-pass denial rate
  under about 5% to 8%; anything drifting past 10% gets attention.
- **Who is causing it, and why?** Payers behave differently, and reasons cluster by
  department. The *Payer Wall of Shame* answers *who*; the *Root Cause* breakdown answers
  *why*; the account filter answers *where*.
- **Are we fixing problems or just working them?** *Clean Claim Rate* is the leading
  indicator. Rework can hide a bad process; clean claim rate exposes it.

**Why the business bucket matters more than the raw code.** A payer returns a CARC code
such as CO-197. An executive cannot act on "CO-197". They can act on "authorizations are
being missed at the front desk on UnitedHealthcare patients at Lecom". The mapping table in
`logic.py` is the bridge between the remittance file and a decision.
"""

DOMAIN_MAPPING_MD = """
**This is where your coding and billing years do the analyst's hardest job.** The dataset
arrives as codes and dollar amounts. Deciding what a code *means for the business* is not a
Python skill, it is a domain skill, and you already have it.

- **Lecom.** You know a physician-group front desk lives on eligibility checks. When you see
  CO-27 (coverage terminated) and CO-31 (patient not identified) piling up, you do not read
  "two random codes", you read *the desk is not verifying coverage at check-in*. That is why
  those codes sit in **Eligibility & Front-End Errors** and the owner is patient access, not
  coding.
- **ACMH.** A hospital account bills high-dollar procedures, and medical-necessity denials
  (CO-50) and bundling denials (CO-97) are the classic hospital pattern. You know an appeal on
  a \\$12,000 procedure is worth a coder's afternoon and a \\$180 lab is not, so the analyst
  question becomes *dollars* at risk, not just counts. That is why every table here carries
  Revenue at Risk beside the count.
- **Tia Health.** A clinic that batches claims late runs into CO-29 (timely filing) and CO-18
  (duplicates). Neither is a coding error. They are workflow failures, so they belong in
  **Operational Workflow Issues**, and the fix is a submission-lag alert, not a coder retrain.

**Reading the mapping table below, notice three habits an analyst keeps:**

1. **Normalize before you map.** `co16`, `CO 16` and `CO-016` are the same code. The
   function `normalize_denial_code()` fixes formatting first, then `categorize_denial()`
   looks it up. Never map on raw text.
2. **Every bucket has an owner.** If you cannot name who fixes it, it is not a useful bucket.
3. **Unknown codes are flagged, never dropped.** A code that is not in the table lands in
   *Needs Review*, so the pie chart cannot quietly hide 4% of denials.
"""

HOW_TO_STUDY_MD = """
**Where to look in the code**

| File | What to read for |
|---|---|
| `denial_dashboard/logic.py` | The mapping table, the KPI definitions, the SQL. Start here. |
| `denial_dashboard/data.py` | How the mock world is built and which "stories" were planted in it. |
| `denial_dashboard/charts.py` | Why each chart uses the colours it does. |
| `denial_dashboard/sql_lab.py` | The twelve SQL lessons, their solutions, and how the checker compares results. |
| `app.py` | How filters flow into every number on the page. |

**Exercises**

1. Filter to **ICN PECL** and switch the trend to *By root cause*. Find the month the
   registration system changed. Write the two-sentence note you would send the account manager.
2. Filter to **ACMH** only. Compare the root-cause pie to the *Revenue at Risk* column in the
   payer table. Why do counts and dollars tell different stories?
3. Change the random seed in the sidebar. Which findings survive? Those are the structural
   ones. The ones that vanish were noise. Learning to tell the two apart is most of the job.
4. Add a new CARC code to `DENIAL_CODES` (try PR-1, deductible). Decide its bucket and owner.
   Reload the page and see where it lands.
"""

PANDAS_TOP_PAYERS = '''def top_denying_payers(df, n=5, min_claims=50):
    g = (df.groupby("Payer")
           .agg(total_claims=("Claim_ID", "count"),
                denied_claims=("Is_Denied", "sum"),
                revenue_at_risk=("Denied_Amount", "sum"))
           .reset_index())
    g["denial_rate_pct"] = 100.0 * g["denied_claims"] / g["total_claims"]
    g = g[g["total_claims"] >= min_claims]          # HAVING COUNT(*) >= 50
    return (g.sort_values(["denial_rate_pct", "revenue_at_risk"], ascending=False)
             .head(n))                                # ORDER BY ... DESC LIMIT 5'''

SQL_WALKTHROUGH_MD = """
**How to read the query, clause by clause**

- `SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END)` is the SQL idiom for
  "count only the denied rows". It is the same trick as summing a True/False column in pandas.
- The denial rate is that sum divided by `COUNT(*)`. The `100.0` forces decimal division;
  `100 * 37 / 412` in many databases silently returns `8`, not `8.98`.
- `GROUP BY payer` turns 5,000 claim rows into one row per payer. Every column in the
  `SELECT` is either the grouping column or an aggregate. That rule is the one new analysts
  trip on most.
- `HAVING` filters *after* grouping. `WHERE` filters rows before. A payer with 12 claims and
  3 denials shows a 25% rate that means nothing, so `HAVING COUNT(*) >= 50` removes it.
- `ORDER BY denial_rate_pct DESC, revenue_at_risk DESC` ranks worst first and breaks ties
  by dollars.

The query above runs for real, against an in-memory SQLite copy of the filtered claims,
each time the page renders. The pandas version underneath produces the same table; the
dashboard uses pandas because the data is already in memory, but the SQL is what you would
write against the billing system's warehouse.

**Want to be able to write this yourself?** The **SQL Lab** tab teaches it in twelve steps,
from `SELECT` to this exact report, with a checker that tells you what is off, and a practice
test of up to 50 generated questions under every lesson.
"""


def _fmt_money(v: float) -> str:
    return "${:,.0f}".format(v)


def generate_insights(df: pd.DataFrame) -> list:
    """Three worked interpretations of the data currently in view.

    Each is a dict with title, finding, so_what and action. Falls back to a note when the
    filtered slice is too small to say anything responsible.
    """
    out = []
    den = df[df["Is_Denied"]]
    if len(den) < 20:
        return [{
            "title": "Not enough denials in view to interpret",
            "finding": "Fewer than 20 denied claims match the current filters.",
            "so_what": "Small slices produce big, meaningless percentages.",
            "action": "Widen the account or payer filter before drawing conclusions.",
        }]

    # 1. The sharpest one-month eligibility spike for any account -----------------------
    elig = den[den["Root_Cause_Category"] == CATEGORY_ELIGIBILITY]
    all_by = den.groupby(["Account_Name", "Submission_Month"]).size().rename("all_denials")
    elig_by = elig.groupby(["Account_Name", "Submission_Month"]).size().rename("elig_denials")
    m = pd.concat([all_by, elig_by], axis=1).fillna(0).reset_index()
    if len(m):
        acct_tot = m.groupby("Account_Name")[["all_denials", "elig_denials"]].transform("sum")
        other_all = acct_tot["all_denials"] - m["all_denials"]
        other_elig = acct_tot["elig_denials"] - m["elig_denials"]
        m["share"] = m["elig_denials"] / m["all_denials"]
        m["baseline"] = (other_elig / other_all).where(other_all > 0, m["share"])
        # Rank by how many eligibility denials exceed what the account's other months predict.
        # A count, not a percentage, so a real incident beats a small-sample fluke.
        m["excess"] = m["elig_denials"] - m["baseline"] * m["all_denials"]
        cand = m[(m["elig_denials"] >= 5) & (m["all_denials"] >= 10) & (m["excess"] >= 3)]
        if len(cand):
            r = cand.sort_values("excess", ascending=False).iloc[0]
            month = pd.Timestamp(r["Submission_Month"]).strftime("%B %Y")
            out.append({
                "title": "A one-month spike points at a process change, not a payer",
                "finding": (
                    "In {m}, {s:.0%} of {a}'s denials were Eligibility & Front-End errors ({e:.0f} of {t:.0f}), "
                    "against {b:.0%} across its other months."
                ).format(m=month, s=r["share"], a=r["Account_Name"], e=r["elig_denials"], t=r["all_denials"], b=r["baseline"]),
                "so_what": (
                    "Payers do not change their rules for one account for one month. A jump this sharp almost "
                    "always traces to something inside the account: a registration system change, new front-desk "
                    "staff, or a plan migration that moved member IDs."
                ),
                "action": (
                    "Pull that month's registration and eligibility-check logs for {a} and ask the account manager "
                    "what changed. Then: {fix}"
                ).format(a=r["Account_Name"], fix=CATEGORY_ACTION[CATEGORY_ELIGIBILITY]),
            })

    # 2. The worst payer and what it is denying for --------------------------------------
    rates = rate_by(df, "Payer")
    rates = rates[rates["total_claims"] >= 30]
    if len(rates):
        worst = rates.iloc[0]
        pd_ = den[den["Payer"] == worst["Payer"]]
        mix = pd_["Root_Cause_Category"].value_counts(normalize=True)
        top_cat = mix.index[0] if len(mix) else CATEGORY_CODING
        overall = 100.0 * len(den) / len(df)
        out.append({
            "title": "Rank payers by rate, then ask what they are denying for",
            "finding": (
                "{p} denies {r:.1f}% of the claims in view ({d:,} of {t:,}), against {o:.1f}% for all payers in view. "
                "{s:.0%} of {p}'s denials are {c}."
            ).format(p=worst["Payer"], r=worst["denial_rate_pct"], d=int(worst["denied_claims"]),
                     t=int(worst["total_claims"]), o=overall, s=mix.iloc[0] if len(mix) else 0, c=CATEGORY_SHORT[top_cat]),
            "so_what": (
                "A high rate alone is a complaint. A high rate with a dominant reason is a work plan: the owner is "
                "{owner}, and the payer-relations conversation has a specific ask."
            ).format(owner=CATEGORY_OWNER[top_cat].lower()),
            "action": (
                "Export {p}'s denied claims for the top reason, bring the list to the next {p} payer call, and in "
                "parallel: {fix}"
            ).format(p=worst["Payer"], fix=CATEGORY_ACTION[top_cat]),
        })

    # 3. Counts versus dollars ------------------------------------------------------------
    summ = root_cause_summary(df)
    summ = summ[summ["Root_Cause_Category"].isin(CATEGORIES)]
    if len(summ) >= 2:
        summ = summ.assign(gap=summ["share_of_dollars_pct"] - summ["share_of_denials_pct"])
        top = summ.sort_values("gap", ascending=False).iloc[0]
        cat = top["Root_Cause_Category"]
        by_acct = (den[den["Root_Cause_Category"] == cat].groupby("Account_Name")["Billed_Amount"].sum()
                   .sort_values(ascending=False))
        lead_acct = by_acct.index[0] if len(by_acct) else "one account"
        lead_share = (by_acct.iloc[0] / by_acct.sum()) if len(by_acct) and by_acct.sum() else 0
        out.append({
            "title": "Counts tell you where the work is; dollars tell you where the money is",
            "finding": (
                "{c} is {n:.0f}% of denied claims but {d:.0f}% of revenue at risk ({money}). "
                "{a} alone carries {s:.0%} of those dollars."
            ).format(c=CATEGORY_SHORT[cat], n=top["share_of_denials_pct"], d=top["share_of_dollars_pct"],
                     money=_fmt_money(top["revenue_at_risk"]), a=lead_acct, s=lead_share),
            "so_what": (
                "A denials team that works its queue oldest-first or most-frequent-first will spend its day on "
                "small claims while the large ones age toward the appeal deadline."
            ),
            "action": (
                "Sort the appeal work queue by billed amount within filing deadline, and put a pre-bill review on "
                "{a}'s procedures above $5,000. Owner: {owner}."
            ).format(a=lead_acct, owner=CATEGORY_OWNER[cat].lower()),
        })

    return out[:3]
