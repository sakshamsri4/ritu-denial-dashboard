"""Mock claims generator: the "extract from the billing system".

Every number here is invented. The generator is seeded, so the same seed always
produces the same claims and the dashboard is reproducible for study.

The story the mock world tells (so the charts have something to find):
  * Five payers with different baseline denial rates. UnitedHealthcare denies most,
    Medicare least.
  * Five client accounts with different weak spots:
      Lecom         eligibility problems at the front desk
      ACMH          coding and medical-necessity mismatches on high-dollar hospital claims
      Tia Health    timely-filing and duplicate submissions (workflow)
      ICN PECL      a one-month eligibility spike after a registration system change
      Xtend Health  balanced, the control group
  * One claim in five arrives with a "messy" denial code (co-16, CO16, CO 16), the
    way 835 remittance extracts often look after a trip through a spreadsheet.
    logic.normalize_denial_code() repairs them.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .logic import (CATEGORIES, CATEGORY_CODING, CATEGORY_ELIGIBILITY, CATEGORY_OPERATIONS,
                    DENIAL_CODES)

PAYERS = ["Medicare", "UnitedHealthcare", "Aetna", "Cigna", "Humana"]
PAYER_VOLUME = [0.30, 0.22, 0.18, 0.16, 0.14]
PAYER_DENIAL_RATE = {"Medicare": 0.07, "UnitedHealthcare": 0.16, "Aetna": 0.12, "Cigna": 0.11, "Humana": 0.09}
# How a payer tilts the reason mix (multipliers on the account mix below).
PAYER_CATEGORY_TILT = {
    "Medicare": {CATEGORY_ELIGIBILITY: 0.7, CATEGORY_CODING: 1.4, CATEGORY_OPERATIONS: 1.0},
    "UnitedHealthcare": {CATEGORY_ELIGIBILITY: 1.4, CATEGORY_CODING: 0.9, CATEGORY_OPERATIONS: 0.9},
    "Aetna": {CATEGORY_ELIGIBILITY: 1.0, CATEGORY_CODING: 1.1, CATEGORY_OPERATIONS: 0.9},
    "Cigna": {CATEGORY_ELIGIBILITY: 0.9, CATEGORY_CODING: 0.9, CATEGORY_OPERATIONS: 1.3},
    "Humana": {CATEGORY_ELIGIBILITY: 1.1, CATEGORY_CODING: 1.0, CATEGORY_OPERATIONS: 1.0},
}

ACCOUNTS = ["Xtend Health", "Tia Health", "ACMH", "ICN PECL", "Lecom"]
ACCOUNT_VOLUME = [0.26, 0.22, 0.20, 0.17, 0.15]
ACCOUNT_RATE_SHIFT = {"Xtend Health": 0.00, "Tia Health": 0.02, "ACMH": 0.01, "ICN PECL": 0.01, "Lecom": 0.02}
# ACMH is a hospital: bigger claims. Lecom and Tia are clinics: smaller ones.
ACCOUNT_AMOUNT_SCALE = {"Xtend Health": 1.0, "Tia Health": 0.8, "ACMH": 2.4, "ICN PECL": 1.1, "Lecom": 0.7}
ACCOUNT_CATEGORY_MIX = {
    "Xtend Health": {CATEGORY_ELIGIBILITY: 35, CATEGORY_CODING: 40, CATEGORY_OPERATIONS: 25},
    "Tia Health": {CATEGORY_ELIGIBILITY: 25, CATEGORY_CODING: 30, CATEGORY_OPERATIONS: 45},
    "ACMH": {CATEGORY_ELIGIBILITY: 20, CATEGORY_CODING: 60, CATEGORY_OPERATIONS: 20},
    "ICN PECL": {CATEGORY_ELIGIBILITY: 40, CATEGORY_CODING: 35, CATEGORY_OPERATIONS: 25},
    "Lecom": {CATEGORY_ELIGIBILITY: 55, CATEGORY_CODING: 30, CATEGORY_OPERATIONS: 15},
}

# Within a bucket, which codes show up most.
CODE_WEIGHTS = {"CO-27": 3, "CO-31": 2, "CO-22": 1, "CO-197": 2,
                "CO-16": 3, "CO-50": 3, "CO-97": 2, "CO-4": 1, "CO-11": 1,
                "CO-29": 3, "CO-18": 2}

# The planted incident: ICN PECL's registration system migration, in the 4th of the 6 months.
SPIKE_ACCOUNT = "ICN PECL"
SPIKE_MONTH_INDEX = 3
SPIKE_EXTRA_DENIAL_RATE = 0.12
SPIKE_ELIGIBILITY_MULTIPLIER = 3.0

MESSY_CODE_SHARE = 0.20
AMOUNT_MIN, AMOUNT_MAX = 150.0, 25000.0


def _messy(code: str, rng: np.random.Generator) -> str:
    """Return the code as a spreadsheet might have mangled it, one time in five."""
    if rng.random() >= MESSY_CODE_SHARE:
        return code
    grp, num = code.split("-")
    variants = [code.lower(), grp + num, "%s %s" % (grp, num), code + " "]
    return variants[int(rng.integers(0, len(variants)))]


def generate_claims(n: int = 5000, seed: int = 42, end_date: date | None = None) -> pd.DataFrame:
    """Build `n` mock claims covering the six calendar months ending on `end_date` (default today)."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(end_date or date.today()).normalize()
    start = (end.to_period("M") - 5).to_timestamp()
    span_days = int((end - start).days)

    payer = rng.choice(PAYERS, size=n, p=PAYER_VOLUME)
    account = rng.choice(ACCOUNTS, size=n, p=ACCOUNT_VOLUME)
    sub_date = start + pd.to_timedelta(rng.integers(0, span_days + 1, size=n), unit="D")
    month_index = (sub_date.year - start.year) * 12 + (sub_date.month - start.month)

    scale = np.array([ACCOUNT_AMOUNT_SCALE[a] for a in account])
    amount = rng.lognormal(mean=np.log(900.0), sigma=0.95, size=n) * scale
    amount = np.clip(amount, AMOUNT_MIN, AMOUNT_MAX).round(2)

    spike = (account == SPIKE_ACCOUNT) & (month_index == SPIKE_MONTH_INDEX)
    p_deny = (np.array([PAYER_DENIAL_RATE[p] for p in payer])
              + np.array([ACCOUNT_RATE_SHIFT[a] for a in account])
              + np.where(spike, SPIKE_EXTRA_DENIAL_RATE, 0.0))
    denied = rng.random(n) < p_deny

    codes_by_cat = {cat: [c for c, m in DENIAL_CODES.items() if m["category"] == cat] for cat in CATEGORIES}
    raw_code = np.full(n, "", dtype=object)
    description = np.full(n, "", dtype=object)
    for i in np.flatnonzero(denied):
        acct, pyr = account[i], payer[i]
        w = np.array([ACCOUNT_CATEGORY_MIX[acct][c] * PAYER_CATEGORY_TILT[pyr][c] for c in CATEGORIES], dtype=float)
        if spike[i]:
            w[CATEGORIES.index(CATEGORY_ELIGIBILITY)] *= SPIKE_ELIGIBILITY_MULTIPLIER
        cat = CATEGORIES[int(rng.choice(len(CATEGORIES), p=w / w.sum()))]
        pool = codes_by_cat[cat]
        pw = np.array([CODE_WEIGHTS[c] for c in pool], dtype=float)
        code = pool[int(rng.choice(len(pool), p=pw / pw.sum()))]
        raw_code[i] = _messy(code, rng)
        description[i] = DENIAL_CODES[code]["description"]

    # Paid claims that needed a second submission before paying are not "clean".
    resubmitted = np.where(denied, rng.random(n) < 0.10, rng.random(n) < 0.14)

    df = pd.DataFrame({
        "Account_Name": account,
        "Payer": payer,
        "Claim_Submission_Date": sub_date,
        "Billed_Amount": amount,
        "Claim_Status": np.where(denied, "Denied", "Paid"),
        "Denial_Reason_Code": raw_code,
        "Denial_Reason_Description": description,
        "Submission_Count": np.where(resubmitted, 2, 1),
    }).sort_values("Claim_Submission_Date", kind="stable").reset_index(drop=True)
    df.insert(0, "Claim_ID", ["CLM-%07d" % (1000001 + i) for i in range(len(df))])
    return df


def period_bounds(df: pd.DataFrame):
    """First and last submission date in the frame, as Timestamps."""
    d = pd.to_datetime(df["Claim_Submission_Date"])
    return d.min(), d.max()
