#!/usr/bin/env python3
"""Clean the messy raw claims file and build the dashboard's data.

Reads  data/raw_claims.csv
Writes data/clean_claims.csv      - one row per claim, standardized
       data/cleaning_log.json     - what each step removed or repaired
       data/dashboard_data.json   - aggregates the dashboard renders

Definitions used throughout:
  * A claim is "adjudicated" when its final status is Paid or Denied.
  * denial_rate = denied / adjudicated. Pending claims are excluded from
    both numerator and denominator so open work doesn't distort the rate.
  * "Rejected" (clearinghouse) and "Denied" (payer) are folded together as
    Denied; the raw spelling is kept in raw_status for audit.
  * A claim resubmitted after a denial is counted once, by its latest
    submission. The earlier denial is still visible in raw_claims.csv.
"""
import json
import os
import re
from datetime import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
RAW = os.path.join(DATA, "raw_claims.csv")
CLEAN = os.path.join(DATA, "clean_claims.csv")
LOG = os.path.join(DATA, "cleaning_log.json")
DASH = os.path.join(DATA, "dashboard_data.json")

# ---------------------------------------------------------------- reference tables
# Keyword order matters: "Humana Medicare Adv" must map to Humana, not Medicare.
PAYER_KEYWORDS = [
    ("humana", "Humana"),
    ("medicaid", "Medicaid"),
    ("medicare", "Medicare"),
    ("cms", "Medicare"),
    ("bcbs", "Blue Cross Blue Shield"),
    ("blue cross", "Blue Cross Blue Shield"),
    ("bluecross", "Blue Cross Blue Shield"),
    ("anthem", "Blue Cross Blue Shield"),
    ("united", "UnitedHealthcare"),
    ("uhc", "UnitedHealthcare"),
    ("aetna", "Aetna"),
    ("cigna", "Cigna"),
    ("kaiser", "Kaiser Permanente"),
]
PAYER_ORDER = ["Medicare", "Blue Cross Blue Shield", "UnitedHealthcare", "Aetna",
               "Medicaid", "Cigna", "Humana", "Kaiser Permanente"]

STATUS_MAP = {
    "paid": "Paid", "pd": "Paid",
    "denied": "Denied", "deny": "Denied", "rejected": "Denied",
    "pending": "Pending", "in process": "Pending", "submitted": "Pending",
}

APPEAL_MAP = {
    "not appealed": "Not Appealed", "none": "Not Appealed", "n/a": "Not Appealed",
    "appealed - pending": "Appealed - Pending", "appeal pending": "Appealed - Pending", "appealed-pending": "Appealed - Pending",
    "appealed - overturned": "Appealed - Overturned", "overturned": "Appealed - Overturned", "appeal won": "Appealed - Overturned",
    "appealed - upheld": "Appealed - Upheld", "upheld": "Appealed - Upheld", "appeal lost": "Appealed - Upheld",
}

# CARC number -> (denial category, canonical description). Keyed on the number
# because CO-18 and OA-18, or CO-27 and PR-27, describe the same thing.
CARC = {
    "27": ("Eligibility", "Expenses incurred after coverage terminated"),
    "26": ("Eligibility", "Expenses incurred prior to coverage"),
    "31": ("Eligibility", "Patient cannot be identified as our insured"),
    "200": ("Eligibility", "Expenses incurred during lapse in coverage"),
    "177": ("Eligibility", "Patient has not met the required eligibility requirements"),
    "4": ("Coding Mismatch", "Procedure code is inconsistent with the modifier used"),
    "11": ("Coding Mismatch", "Diagnosis is inconsistent with the procedure"),
    "181": ("Coding Mismatch", "Procedure code was invalid on the date of service"),
    "182": ("Coding Mismatch", "Procedure modifier was invalid on the date of service"),
    "146": ("Coding Mismatch", "Diagnosis was invalid for the date(s) of service reported"),
    "16": ("Missing Information", "Claim/service lacks information or has submission/billing error(s)"),
    "252": ("Missing Information", "An attachment/other documentation is required to adjudicate this claim"),
    "226": ("Missing Information", "Information requested from the billing/rendering provider was not provided"),
    "197": ("Prior Authorization", "Precertification/authorization/notification absent"),
    "15": ("Prior Authorization", "Authorization number is missing, invalid, or does not apply"),
    "198": ("Prior Authorization", "Precertification/authorization exceeded"),
    "50": ("Medical Necessity", "Non-covered services: not deemed a medical necessity by the payer"),
    "167": ("Medical Necessity", "This (these) diagnosis(es) is (are) not covered"),
    "151": ("Medical Necessity", "Information submitted does not support this many/frequency of services"),
    "29": ("Timely Filing", "The time limit for filing has expired"),
    "18": ("Duplicate Claim", "Exact duplicate claim/service"),
    "96": ("Non-Covered Service", "Non-covered charge(s)"),
    "204": ("Non-Covered Service", "Service not covered under the patient's current benefit plan"),
    "49": ("Non-Covered Service", "Routine/preventive exam or screening procedure done with a routine exam"),
    "22": ("Other", "Care may be covered by another payer per coordination of benefits"),
    "97": ("Other", "Benefit for this service is included in the payment for another service"),
    "45": ("Other", "Charge exceeds fee schedule/maximum allowable"),
    "B7": ("Other", "Provider was not certified/eligible to be paid for this procedure"),
}
CATEGORY_ORDER = ["Eligibility", "Coding Mismatch", "Missing Information", "Prior Authorization",
                  "Medical Necessity", "Timely Filing", "Duplicate Claim", "Non-Covered Service", "Other"]
# What a denial-management team actually does about each category.
CATEGORY_ACTION = {
    "Eligibility": "Verify coverage at scheduling; re-check 48h before the visit.",
    "Coding Mismatch": "Coder review of CPT/ICD/modifier pairing before submission.",
    "Missing Information": "Front-end claim scrubber edits; attach documentation up front.",
    "Prior Authorization": "Auth-required list by payer; obtain and record auth before service.",
    "Medical Necessity": "Diagnosis documentation and LCD/NCD checks for high-value procedures.",
    "Timely Filing": "Submission-lag alerts; work the aging queue weekly.",
    "Duplicate Claim": "Suppress resubmits until the original adjudicates; fix batch logic.",
    "Non-Covered Service": "Benefit check and ABN/waiver before service.",
    "Other": "Route to payer-relations for COB, bundling and fee-schedule disputes.",
}

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%Y%m%d")


# ---------------------------------------------------------------- helpers
def parse_date(s):
    s = str(s).strip()
    if not s:
        return pd.NaT
    for fmt in DATE_FORMATS:
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return pd.NaT


def normalize_payer(s):
    s = re.sub(r"\s+", " ", str(s)).strip().lower()
    if s in ("", "unknown", "n/a", "null"):
        return None
    for kw, canon in PAYER_KEYWORDS:
        if kw in s:
            return canon
    return None


def parse_amount(s):
    s = str(s).strip().replace("$", "").replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return np.nan
    return v if v > 0 else np.nan


CODE_RE = re.compile(r"^\s*([A-Za-z]{2})?\s*-?\s*(B?\d+)\s*$")


def parse_code(s):
    """Return (group, number, group_was_inferred) or (None, None, False)."""
    s = str(s).strip()
    if not s:
        return None, None, False
    m = CODE_RE.match(s)
    if not m:
        return None, None, False
    grp, num = m.group(1), m.group(2).upper()
    num = num.lstrip("0") or "0"
    if grp is None:
        return "CO", num, True
    return grp.upper(), num, False


def normalize_icd(s):
    s = str(s).strip().upper()
    if re.match(r"^[A-Z]\d{2}\d+$", s):  # dot was dropped
        return s[:3] + "." + s[3:]
    return s


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


# ---------------------------------------------------------------- pipeline
def main():
    log = {"source": "data/raw_claims.csv", "generated": datetime.now().strftime("%Y-%m-%d"), "steps": []}

    def step(name, removed, repaired, detail):
        log["steps"].append({"step": name, "rows_removed": int(removed), "values_repaired": int(repaired), "detail": detail})

    df = pd.read_csv(RAW, dtype=str, keep_default_na=False)
    raw_rows = len(df)
    log["raw_rows"] = raw_rows

    # 1. whitespace + case hygiene on every text column
    trimmed = 0
    for c in df.columns:
        stripped = df[c].str.strip()
        trimmed += int((stripped != df[c]).sum())
        df[c] = stripped
    step("Trim whitespace", 0, trimmed, "Leading/trailing spaces removed from all text fields.")

    # 2. drop test records
    is_test = df["claim_id"].str.startswith("TST-") | df["patient_id"].str.upper().str.startswith("TEST")
    df = df[~is_test].copy()
    step("Remove test records", is_test.sum(), 0, "claim_id starting TST- or patient_id starting TEST.")

    # 3. payer normalization
    df["raw_payer"] = df["payer"]
    df["payer"] = df["raw_payer"].map(normalize_payer)
    variants = df.loc[df["payer"].notna()].groupby("payer")["raw_payer"].nunique()
    unmapped = df["payer"].isna()
    unmapped_values = sorted(set(df.loc[unmapped, "raw_payer"].str.strip().replace("", "<blank>")))
    df = df[~unmapped].copy()
    step("Standardize payer names", unmapped.sum(), int((df["raw_payer"] != df["payer"]).sum()),
         "%d spelling variants collapsed to %d payers. Dropped %d rows whose payer was %s."
         % (int(variants.sum()), len(variants), int(unmapped.sum()),
            ", ".join(v.replace("<blank>", "blank") for v in unmapped_values)))

    # 4. dates
    for c in ("service_date", "submission_date"):
        df[c] = df[c].map(parse_date)
    bad_dates = df["service_date"].isna() | df["submission_date"].isna()
    df = df[~bad_dates].copy()
    df["days_to_submit"] = (df["submission_date"] - df["service_date"]).dt.days
    step("Parse mixed date formats", bad_dates.sum(), len(df) * 2,
         "ISO, MM/DD/YYYY, DD-Mon-YYYY and YYYYMMDD parsed to one date type.")

    # 5. status
    df["raw_status"] = df["claim_status"]
    n_status_variants = int(df["raw_status"].str.strip().nunique())
    df["claim_status"] = df["raw_status"].str.lower().str.strip().map(STATUS_MAP)
    no_status = df["claim_status"].isna()
    df = df[~no_status].copy()
    step("Standardize claim status", no_status.sum(), int((df["raw_status"] != df["claim_status"]).sum()),
         "%d spellings mapped to Paid / Denied / Pending; 'Rejected' folded into Denied. %d rows with a blank status dropped."
         % (n_status_variants, int(no_status.sum())))

    # 6. amounts
    df["raw_amount"] = df["billed_amount"]
    df["billed_amount"] = df["raw_amount"].map(parse_amount)
    bad_amt = df["billed_amount"].isna()
    step("Parse billed amounts", 0, int((df["raw_amount"].str.contains(r"[$,]") | bad_amt).sum()),
         "Currency symbols and thousands separators removed. %d non-positive or non-numeric amounts set to null "
         "(kept for rate metrics, excluded from dollar totals)." % int(bad_amt.sum()))

    # 7. denial codes
    parsed = df["denial_code"].map(parse_code)
    df["carc_group"] = [p[0] for p in parsed]
    df["carc_number"] = [p[1] for p in parsed]
    inferred = sum(1 for p in parsed if p[2])
    df["denial_code"] = np.where(df["carc_number"].notna(), df["carc_group"].fillna("") + "-" + df["carc_number"].fillna(""), "")
    stale = (df["claim_status"] != "Denied") & (df["denial_code"] != "")
    df.loc[stale, ["denial_code", "carc_group", "carc_number", "denial_reason", "appeal_status"]] = ""
    df.loc[stale, ["carc_group", "carc_number"]] = None
    df["denial_category"] = df["carc_number"].map(lambda n: CARC[n][0] if n in CARC else None)
    df["denial_reason"] = df["carc_number"].map(lambda n: CARC[n][1] if n in CARC else "")
    unknown_code = (df["claim_status"] == "Denied") & df["denial_category"].isna()
    df.loc[unknown_code, "denial_category"] = "Other"
    df.loc[df["claim_status"] != "Denied", "denial_category"] = ""
    code_detail = ("CO16, co-16, 'CO 16', 16 and CO-016 unified to GROUP-NUMBER; %d codes without a group assumed CO; "
                   "%d stale codes on paid claims cleared." % (inferred, int(stale.sum())))
    if int(unknown_code.sum()):
        code_detail += " %d unrecognized codes filed as Other." % int(unknown_code.sum())
    step("Normalize denial codes", 0, int((df["claim_status"] == "Denied").sum()), code_detail)

    # 8. appeal status
    df["appeal_status"] = df["appeal_status"].str.lower().str.strip().map(APPEAL_MAP).fillna("")
    df.loc[df["claim_status"] != "Denied", "appeal_status"] = ""

    # 9. procedure / diagnosis codes
    df["cpt_code"] = df["cpt_code"].str.upper().str.strip()
    icd_before = df["icd10_code"].copy()
    df["icd10_code"] = df["icd10_code"].map(normalize_icd)
    step("Normalize CPT and ICD-10", 0, int((icd_before != df["icd10_code"]).sum()),
         "Upper-cased; ICD-10 codes missing the decimal had it restored.")

    # 10. duplicates: exact copies first, then resubmissions (keep latest submission)
    key_cols = ["claim_id", "submission_date", "raw_status", "denial_code"]
    exact = df.duplicated(subset=key_cols, keep="first")
    df = df[~exact].copy()
    df = df.sort_values(["claim_id", "submission_date"])
    resub = df.duplicated(subset=["claim_id"], keep="last")
    df = df[~resub].copy()
    step("Remove duplicates", exact.sum() + resub.sum(), 0,
         "%d exact duplicate rows dropped. %d resubmitted claims collapsed to their latest submission."
         % (int(exact.sum()), int(resub.sum())))

    df["service_month"] = df["service_date"].dt.strftime("%Y-%m")
    df = df.sort_values(["service_date", "claim_id"]).reset_index(drop=True)
    log["clean_rows"] = len(df)

    out_cols = ["claim_id", "patient_id", "payer", "raw_payer", "service_line", "rendering_provider", "provider_npi",
                "service_date", "submission_date", "days_to_submit", "service_month", "cpt_code", "icd10_code",
                "billed_amount", "claim_status", "raw_status", "denial_code", "denial_category", "denial_reason",
                "appeal_status"]
    out = df[out_cols].copy()
    out["service_date"] = out["service_date"].dt.strftime("%Y-%m-%d")
    out["submission_date"] = out["submission_date"].dt.strftime("%Y-%m-%d")
    out.to_csv(CLEAN, index=False)

    # ---------------------------------------------------------------- aggregates
    adj = df[df["claim_status"].isin(["Paid", "Denied"])]
    den = df[df["claim_status"] == "Denied"]
    pending = df[df["claim_status"] == "Pending"]

    kpis = {
        "claims": int(len(df)),
        "adjudicated": int(len(adj)),
        "denied": int(len(den)),
        "pending": int(len(pending)),
        "denial_rate": pct(len(den), len(adj)),
        "billed_total": round(float(adj["billed_amount"].sum()), 2),
        "denied_dollars": round(float(den["billed_amount"].sum()), 2),
        "denied_dollar_share": pct(den["billed_amount"].sum(), adj["billed_amount"].sum()),
        "appealed": int(den["appeal_status"].str.startswith("Appealed").sum()),
        "overturned": int((den["appeal_status"] == "Appealed - Overturned").sum()),
        "upheld": int((den["appeal_status"] == "Appealed - Upheld").sum()),
        "appeal_pending": int((den["appeal_status"] == "Appealed - Pending").sum()),
        "not_appealed": int((den["appeal_status"] == "Not Appealed").sum()),
        "period_start": df["service_date"].min().strftime("%Y-%m-%d"),
        "period_end": df["service_date"].max().strftime("%Y-%m-%d"),
    }
    kpis["overturn_rate"] = pct(kpis["overturned"], kpis["overturned"] + kpis["upheld"])

    by_payer = []
    for p in PAYER_ORDER:
        a = adj[adj["payer"] == p]
        d = den[den["payer"] == p]
        cat_counts = d["denial_category"].value_counts()
        top = cat_counts.index[0] if len(cat_counts) else ""
        by_payer.append({
            "payer": p,
            "claims": int(len(a)),
            "denied": int(len(d)),
            "denial_rate": pct(len(d), len(a)),
            "billed": round(float(a["billed_amount"].sum()), 2),
            "denied_dollars": round(float(d["billed_amount"].sum()), 2),
            "top_category": top,
            "top_category_share": pct(cat_counts.iloc[0], len(d)) if len(cat_counts) else 0.0,
            "total_claims": int((df["payer"] == p).sum()),
            "pending": int(((df["payer"] == p) & (df["claim_status"] == "Pending")).sum()),
            "appealed": int(d["appeal_status"].str.startswith("Appealed").sum()),
            "overturned": int((d["appeal_status"] == "Appealed - Overturned").sum()),
            "upheld": int((d["appeal_status"] == "Appealed - Upheld").sum()),
            "appeal_pending": int((d["appeal_status"] == "Appealed - Pending").sum()),
            "not_appealed": int((d["appeal_status"] == "Not Appealed").sum()),
        })
    by_payer.sort(key=lambda r: -r["denial_rate"])

    by_category = []
    for c in CATEGORY_ORDER:
        d = den[den["denial_category"] == c]
        by_category.append({
            "category": c,
            "denied": int(len(d)),
            "share": pct(len(d), len(den)),
            "denied_dollars": round(float(d["billed_amount"].sum()), 2),
            "action": CATEGORY_ACTION[c],
        })

    # payer x category matrix, rows in payer denial-rate order
    matrix = []
    for row in by_payer:
        p = row["payer"]
        a = adj[adj["payer"] == p]
        d = den[den["payer"] == p]
        cells = []
        for c in CATEGORY_ORDER:
            n = int((d["denial_category"] == c).sum())
            cells.append({"category": c, "denied": n,
                          "pct_of_payer_denials": pct(n, len(d)),
                          "pct_of_payer_claims": pct(n, len(a))})
        matrix.append({"payer": p, "cells": cells})

    months = sorted(adj["service_month"].unique())
    trend = {"months": months, "overall": [], "by_payer": {}}
    for m in months:
        a = adj[adj["service_month"] == m]
        trend["overall"].append(pct((a["claim_status"] == "Denied").sum(), len(a)))
    for p in PAYER_ORDER:
        series = []
        for m in months:
            a = adj[(adj["service_month"] == m) & (adj["payer"] == p)]
            series.append(pct((a["claim_status"] == "Denied").sum(), len(a)))
        trend["by_payer"][p] = series
    # raw counts behind the rates, so a consumer can recompute exact rates over any span
    trend["counts"] = {"overall": {"adjudicated": [], "denied": []}, "by_payer": {}}
    for m in months:
        a = adj[adj["service_month"] == m]
        trend["counts"]["overall"]["adjudicated"].append(int(len(a)))
        trend["counts"]["overall"]["denied"].append(int((a["claim_status"] == "Denied").sum()))
    for p in PAYER_ORDER:
        ap = adj[adj["payer"] == p]
        trend["counts"]["by_payer"][p] = {
            "adjudicated": [int((ap["service_month"] == m).sum()) for m in months],
            "denied": [int(((ap["service_month"] == m) & (ap["claim_status"] == "Denied")).sum()) for m in months],
        }
    # per-category monthly denial counts, for the reason-over-time view
    trend["by_category"] = {}
    for c in CATEGORY_ORDER:
        trend["by_category"][c] = [int(((den["service_month"] == m) & (den["denial_category"] == c)).sum()) for m in months]

    def code_table(frame, n):
        c = (frame.groupby(["denial_code", "denial_category", "denial_reason"])
             .agg(denied=("claim_id", "count"), denied_dollars=("billed_amount", "sum"))
             .reset_index().sort_values(["denied", "denied_dollars"], ascending=False).head(n))
        return [{"code": r.denial_code, "category": r.denial_category, "reason": r.denial_reason,
                 "denied": int(r.denied), "denied_dollars": round(float(r.denied_dollars), 2)}
                for r in c.itertuples()]

    top_codes = code_table(den, 10)
    codes_by_payer = {p: code_table(den[den["payer"] == p], 5) for p in PAYER_ORDER}

    # service-line view: where the denied dollars concentrate
    by_line = []
    for sl, a in adj.groupby("service_line"):
        d = a[a["claim_status"] == "Denied"]
        by_line.append({"service_line": sl, "claims": int(len(a)), "denied": int(len(d)),
                        "denial_rate": pct(len(d), len(a)),
                        "denied_dollars": round(float(d["billed_amount"].sum()), 2)})
    by_line.sort(key=lambda r: -r["denied_dollars"])

    dashboard = {
        "meta": {
            "title": "Denial Management Dashboard",
            "period": "%s to %s" % (kpis["period_start"], kpis["period_end"]),
            "rate_definition": "Denial rate = denied claims / (paid + denied claims). Pending claims excluded.",
            "raw_rows": raw_rows, "clean_rows": len(df),
        },
        "kpis": kpis,
        "by_payer": by_payer,
        "by_category": by_category,
        "matrix": matrix,
        "trend": trend,
        "top_codes": top_codes,
        "codes_by_payer": codes_by_payer,
        "by_service_line": by_line,
        "cleaning": log,
    }
    with open(DASH, "w") as f:
        json.dump(dashboard, f, indent=2)
    with open(LOG, "w") as f:
        json.dump(log, f, indent=2)

    print("raw rows: %d  clean rows: %d" % (raw_rows, len(df)))
    print("overall denial rate: %.1f%%  denied $: %s" % (kpis["denial_rate"], "{:,.0f}".format(kpis["denied_dollars"])))
    for r in by_payer:
        print("  %-24s %5d claims  %5.1f%% denied  top: %s (%.0f%%)"
              % (r["payer"], r["claims"], r["denial_rate"], r["top_category"], r["top_category_share"]))
    print("by category:")
    for r in by_category:
        print("  %-22s %4d  %5.1f%%" % (r["category"], r["denied"], r["share"]))
    print("cleaning steps:")
    for s in log["steps"]:
        print("  %-28s removed %4d  repaired %5d" % (s["step"], s["rows_removed"], s["values_repaired"]))


if __name__ == "__main__":
    main()
