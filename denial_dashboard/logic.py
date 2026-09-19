"""Healthcare domain logic: denial codes, root-cause buckets, KPIs and groupings.

This is the file a coder-turned-analyst should read first. Everything the
dashboard says about *why* a claim was denied comes from the DENIAL_CODES table
and the three category constants below. Change the mapping here and every
chart, KPI and insight follows.

Vocabulary
----------
CARC   Claim Adjustment Reason Code, the standard code a payer returns on the
       835 remittance to explain a denial or adjustment. "CO" = contractual
       obligation (the provider absorbs it), "PR" = patient responsibility.
Denial rate        denied claims / all claims in view.
Clean claim rate   claims paid on the FIRST submission / all claims in view.
                   A claim that was paid only after rework is not clean.
Revenue at risk    the billed dollars sitting on denied claims.
"""
from __future__ import annotations

import re
import sqlite3

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- root-cause buckets
CATEGORY_ELIGIBILITY = "Eligibility & Front-End Errors"
CATEGORY_CODING = "Clinical Coding & Documentation Mismatches"
CATEGORY_OPERATIONS = "Operational Workflow Issues"
CATEGORY_UNKNOWN = "Needs Review (unmapped code)"

CATEGORIES = [CATEGORY_ELIGIBILITY, CATEGORY_CODING, CATEGORY_OPERATIONS]

CATEGORY_SHORT = {
    CATEGORY_ELIGIBILITY: "Eligibility & Front-End",
    CATEGORY_CODING: "Coding & Documentation",
    CATEGORY_OPERATIONS: "Operational Workflow",
    CATEGORY_UNKNOWN: "Needs Review",
}

# Who owns the fix. This is what turns a chart into an action item.
CATEGORY_OWNER = {
    CATEGORY_ELIGIBILITY: "Patient access / registration desk",
    CATEGORY_CODING: "Coding team and clinical documentation",
    CATEGORY_OPERATIONS: "Billing operations / claims follow-up",
    CATEGORY_UNKNOWN: "Denials analyst (extend the mapping table)",
}

CATEGORY_ACTION = {
    CATEGORY_ELIGIBILITY: (
        "Verify eligibility in real time at scheduling and again 48 hours before the visit; "
        "capture the authorization number in the registration record before service."
    ),
    CATEGORY_CODING: (
        "Route high-dollar procedures through a coder pre-bill review; check CPT, ICD-10 and "
        "modifier pairing against payer policy (LCD/NCD, NCCI edits) before the claim leaves."
    ),
    CATEGORY_OPERATIONS: (
        "Add submission-lag alerts so nothing ages past the payer's filing limit; suppress "
        "resubmissions until the original claim adjudicates."
    ),
    CATEGORY_UNKNOWN: "Look the code up in the CARC list and add it to DENIAL_CODES.",
}

# ---------------------------------------------------------------- the mapping table
# CARC code -> what the payer said, what it means in plain English, and which
# business bucket it belongs to. Keyed on the normalized "GROUP-NUMBER" form.
DENIAL_CODES = {
    "CO-27": {
        "description": "Expenses incurred after coverage terminated",
        "plain_english": "The patient's plan had ended by the date of service.",
        "category": CATEGORY_ELIGIBILITY,
    },
    "CO-31": {
        "description": "Patient cannot be identified as our insured",
        "plain_english": "Member ID, name or date of birth did not match the payer's file.",
        "category": CATEGORY_ELIGIBILITY,
    },
    "CO-22": {
        "description": "Care may be covered by another payer per coordination of benefits",
        "plain_english": "We billed the wrong payer first; another plan is primary.",
        "category": CATEGORY_ELIGIBILITY,
    },
    "CO-197": {
        "description": "Precertification/authorization/notification absent",
        "plain_english": "The service needed prior authorization and none was on file.",
        "category": CATEGORY_ELIGIBILITY,
    },
    "CO-16": {
        "description": "Claim/service lacks information or has submission/billing error(s)",
        "plain_english": "Something required was missing or wrong on the claim form.",
        "category": CATEGORY_CODING,
    },
    "CO-50": {
        "description": "Non-covered services: not deemed a medical necessity by the payer",
        "plain_english": "The diagnosis on the claim did not justify the procedure.",
        "category": CATEGORY_CODING,
    },
    "CO-97": {
        "description": "Benefit for this service is included in the payment for another service",
        "plain_english": "The payer bundled this line into another procedure on the same claim.",
        "category": CATEGORY_CODING,
    },
    "CO-4": {
        "description": "Procedure code is inconsistent with the modifier used",
        "plain_english": "The modifier does not fit the CPT code it was attached to.",
        "category": CATEGORY_CODING,
    },
    "CO-11": {
        "description": "Diagnosis is inconsistent with the procedure",
        "plain_english": "The ICD-10 code does not support the CPT code billed.",
        "category": CATEGORY_CODING,
    },
    "CO-29": {
        "description": "The time limit for filing has expired",
        "plain_english": "The claim reached the payer after its filing deadline.",
        "category": CATEGORY_OPERATIONS,
    },
    "CO-18": {
        "description": "Exact duplicate claim/service",
        "plain_english": "The same claim was sent twice; the second copy was rejected.",
        "category": CATEGORY_OPERATIONS,
    },
}

_CODE_RE = re.compile(r"^\s*([A-Za-z]{2})\s*-?\s*0*(\d+)\s*$")


def normalize_denial_code(raw) -> str | None:
    """Turn 'co16', 'CO 16', 'CO-016' or ' CO-16 ' into 'CO-16'. None if it isn't a code."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    m = _CODE_RE.match(str(raw))
    if not m:
        return None
    return "%s-%s" % (m.group(1).upper(), m.group(2))


def categorize_denial(raw_code) -> str:
    """Map a raw denial code to its business bucket. Unknown codes are flagged, never hidden."""
    code = normalize_denial_code(raw_code)
    if code is None:
        return ""
    meta = DENIAL_CODES.get(code)
    return meta["category"] if meta else CATEGORY_UNKNOWN


def code_table() -> pd.DataFrame:
    """The mapping table as a DataFrame, for display in the training tab."""
    rows = [{"CARC code": code, "Payer wording": m["description"], "Plain English": m["plain_english"],
             "Root-cause bucket": m["category"], "Owner of the fix": CATEGORY_OWNER[m["category"]]}
            for code, m in DENIAL_CODES.items()]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- enrichment
def enrich_claims(df: pd.DataFrame) -> pd.DataFrame:
    """Add the analysis columns every chart uses. Leaves the raw columns untouched."""
    out = df.copy()
    out["Denial_Code_Clean"] = out["Denial_Reason_Code"].map(lambda c: normalize_denial_code(c) or "")
    out["Root_Cause_Category"] = np.where(out["Claim_Status"] == "Denied",
                                          out["Denial_Reason_Code"].map(categorize_denial), "")
    out["Root_Cause_Short"] = out["Root_Cause_Category"].map(lambda c: CATEGORY_SHORT.get(c, c))
    out["Is_Denied"] = out["Claim_Status"] == "Denied"
    out["Is_Clean"] = (out["Claim_Status"] == "Paid") & (out["Submission_Count"] == 1)
    out["Denied_Amount"] = out["Billed_Amount"].where(out["Is_Denied"], 0.0)
    dt = pd.to_datetime(out["Claim_Submission_Date"])
    out["Submission_Month"] = dt.dt.to_period("M").dt.to_timestamp()
    out["Month_Label"] = out["Submission_Month"].dt.strftime("%b %Y")
    return out


# ---------------------------------------------------------------- measures
def _pct(numer, denom) -> float:
    return float(100.0 * numer / denom) if denom else 0.0


def compute_kpis(df: pd.DataFrame) -> dict:
    """Executive KPIs for the claims in view, plus month-over-month deltas when possible."""
    total = int(len(df))
    denied = int(df["Is_Denied"].sum())
    clean = int(df["Is_Clean"].sum())
    k = {
        "total_claims": total,
        "denied_claims": denied,
        "paid_claims": total - denied,
        "clean_claims": clean,
        "revenue_at_risk": float(df["Denied_Amount"].sum()),
        "billed_total": float(df["Billed_Amount"].sum()),
        "denial_rate": _pct(denied, total),
        "clean_claim_rate": _pct(clean, total),
        "delta": None,
    }
    months = sorted(df["Submission_Month"].dropna().unique())
    if len(months) >= 2:
        cur = df[df["Submission_Month"] == months[-1]]
        prev = df[df["Submission_Month"] == months[-2]]
        if len(cur) and len(prev):
            k["delta"] = {
                "label": "%s vs %s" % (pd.Timestamp(months[-1]).strftime("%b"), pd.Timestamp(months[-2]).strftime("%b")),
                "denial_rate_pts": _pct(cur["Is_Denied"].sum(), len(cur)) - _pct(prev["Is_Denied"].sum(), len(prev)),
                "clean_rate_pts": _pct(cur["Is_Clean"].sum(), len(cur)) - _pct(prev["Is_Clean"].sum(), len(prev)),
                "at_risk_change": float(cur["Denied_Amount"].sum() - prev["Denied_Amount"].sum()),
            }
    return k


def rate_by(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Denial rate, volume and dollars at risk per value of `col`, worst first."""
    g = (df.groupby(col)
         .agg(total_claims=("Claim_ID", "count"),
              denied_claims=("Is_Denied", "sum"),
              revenue_at_risk=("Denied_Amount", "sum"))
         .reset_index())
    g["denied_claims"] = g["denied_claims"].astype(int)
    g["denial_rate_pct"] = 100.0 * g["denied_claims"] / g["total_claims"]
    return g.sort_values(["denial_rate_pct", "revenue_at_risk"], ascending=False).reset_index(drop=True)


def root_cause_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Denied claims and dollars per root-cause bucket, in the fixed category order."""
    den = df[df["Is_Denied"]]
    g = (den.groupby("Root_Cause_Category")
         .agg(denied_claims=("Claim_ID", "count"), revenue_at_risk=("Billed_Amount", "sum"))
         .reindex(CATEGORIES + [CATEGORY_UNKNOWN], fill_value=0)
         .reset_index())
    g = g[g["denied_claims"] > 0].copy()
    g["denied_claims"] = g["denied_claims"].astype(int)
    total = g["denied_claims"].sum()
    dollars = g["revenue_at_risk"].sum()
    g["share_of_denials_pct"] = 100.0 * g["denied_claims"] / total if total else 0.0
    g["share_of_dollars_pct"] = 100.0 * g["revenue_at_risk"] / dollars if dollars else 0.0
    g["short"] = g["Root_Cause_Category"].map(CATEGORY_SHORT)
    return g.reset_index(drop=True)


def monthly_trend(df: pd.DataFrame) -> pd.DataFrame:
    g = (df.groupby("Submission_Month")
         .agg(total_claims=("Claim_ID", "count"), denied_claims=("Is_Denied", "sum"),
              revenue_at_risk=("Denied_Amount", "sum"))
         .reset_index().sort_values("Submission_Month"))
    g["denied_claims"] = g["denied_claims"].astype(int)
    g["denial_rate_pct"] = 100.0 * g["denied_claims"] / g["total_claims"]
    g["month_label"] = g["Submission_Month"].dt.strftime("%b %Y")
    return g.reset_index(drop=True)


def monthly_trend_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """Each bucket's contribution to the monthly denial rate (the three lines add up to the total)."""
    totals = df.groupby("Submission_Month")["Claim_ID"].count()
    den = df[df["Is_Denied"]]
    rows = []
    for month, total in totals.items():
        d = den[den["Submission_Month"] == month]
        for cat in CATEGORIES:
            n = int((d["Root_Cause_Category"] == cat).sum())
            rows.append({"Submission_Month": month, "month_label": pd.Timestamp(month).strftime("%b %Y"),
                         "category": cat, "short": CATEGORY_SHORT[cat], "denied_claims": n,
                         "total_claims": int(total), "rate_contribution_pct": _pct(n, total)})
    return pd.DataFrame(rows)


def payer_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """Denied-claim counts, payer by bucket, with a total and dollars at risk. The table twin of the charts."""
    den = df[df["Is_Denied"]]
    if den.empty:
        return pd.DataFrame()
    pv = pd.pivot_table(den, index="Payer", columns="Root_Cause_Short", values="Claim_ID",
                        aggfunc="count", fill_value=0)
    order = [CATEGORY_SHORT[c] for c in CATEGORIES if CATEGORY_SHORT[c] in pv.columns]
    extra = [c for c in pv.columns if c not in order]
    pv = pv[order + extra]
    pv["Total denied"] = pv.sum(axis=1)
    pv["Revenue at risk"] = den.groupby("Payer")["Billed_Amount"].sum().round(0)
    return pv.sort_values("Total denied", ascending=False)


def top_denying_payers(df: pd.DataFrame, n: int = 5, min_claims: int = 50) -> pd.DataFrame:
    """The pandas twin of the SQL in training.py: highest denial rate first, small payers excluded."""
    r = rate_by(df, "Payer")
    r = r[r["total_claims"] >= min_claims]
    return r.head(n).reset_index(drop=True)


# ---------------------------------------------------------------- SQL, run for real
SQL_TOP_PAYERS = """-- Top 5 highest-denying payers for the period in view.
-- One row per payer: volume, denials, denial rate and the dollars sitting on those denials.
SELECT
    payer,
    COUNT(*)                                                         AS total_claims,
    SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END)         AS denied_claims,
    ROUND(100.0 * SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END)
               / COUNT(*), 1)                                        AS denial_rate_pct,
    ROUND(SUM(CASE WHEN claim_status = 'Denied'
                   THEN billed_amount ELSE 0 END), 2)                AS revenue_at_risk
FROM claims
WHERE claim_submission_date BETWEEN '{start}' AND '{end}'
GROUP BY payer
HAVING COUNT(*) >= {min_claims}      -- too few claims and one bad week looks like a trend
ORDER BY denial_rate_pct DESC, revenue_at_risk DESC
LIMIT {n};"""


def sql_top_payers_text(start, end, n: int = 5, min_claims: int = 50) -> str:
    return SQL_TOP_PAYERS.format(start=pd.Timestamp(start).strftime("%Y-%m-%d"),
                                 end=pd.Timestamp(end).strftime("%Y-%m-%d"), n=n, min_claims=min_claims)


def run_sql_top_payers(df: pd.DataFrame, start, end, n: int = 5, min_claims: int = 50) -> pd.DataFrame:
    """Load the claims in view into an in-memory SQLite table and run the query above, verbatim."""
    cols = {"Payer": "payer", "Claim_Status": "claim_status", "Billed_Amount": "billed_amount",
            "Claim_Submission_Date": "claim_submission_date"}
    t = df[list(cols)].rename(columns=cols).copy()
    t["claim_submission_date"] = pd.to_datetime(t["claim_submission_date"]).dt.strftime("%Y-%m-%d")
    con = sqlite3.connect(":memory:")
    try:
        t.to_sql("claims", con, index=False)
        return pd.read_sql_query(sql_top_payers_text(start, end, n, min_claims), con)
    finally:
        con.close()
