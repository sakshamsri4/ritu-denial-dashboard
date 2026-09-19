#!/usr/bin/env python3
"""Generate a deliberately messy mock medical-billing claims file.

Writes data/raw_claims.csv.

Every kind of mess below is intentional and is repaired by clean_claims.py:
  * payer names spelled eight different ways per payer (case, spacing, aliases)
  * four different date formats in the same column
  * billed amounts as "$1,250.00", "1,250.00", "1250", "N/A", negatives
  * claim status spelled many ways ("PAID", "pd", "Rejected", "In Process")
  * denial codes formatted as CO-16, CO16, co-16, "CO 16", "16", CO-016
  * exact duplicate rows and resubmitted claims sharing a claim_id
  * test records that never belonged in production data
  * blank payers, blank statuses, lowercase CPT/ICD codes, ICD codes missing the dot
"""
import csv
import os
import random
from datetime import date, timedelta

SEED = 20260919
N_CLAIMS = 2400
START = date(2025, 9, 1)
END = date(2026, 8, 31)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "raw_claims.csv")

# canonical payer -> (volume weight, base denial probability, messy aliases)
PAYERS = {
    "Medicare": (0.22, 0.07, ["Medicare", "MEDICARE", "Medicare Part B", "CMS Medicare", "medicare ", "Medicare FFS"]),
    "Blue Cross Blue Shield": (0.18, 0.11, ["Blue Cross Blue Shield", "BCBS", "Anthem BCBS", "BlueCross BlueShield", "bcbs", "Blue Cross"]),
    "UnitedHealthcare": (0.16, 0.16, ["UnitedHealthcare", "United Healthcare", "UHC", "United HealthCare Ins", " UnitedHealthcare", "United Health Care"]),
    "Aetna": (0.12, 0.13, ["Aetna", "AETNA", "Aetna Inc.", "aetna", "Aetna Health", "AETNA "]),
    "Medicaid": (0.12, 0.22, ["Medicaid", "MEDICAID", "State Medicaid", "Medicaid MCO", "medicaid", "Medicaid Managed Care"]),
    "Cigna": (0.09, 0.12, ["Cigna", "CIGNA", "Cigna Healthcare", "cigna ", "CIGNA Health", "Cigna HealthCare"]),
    "Humana": (0.07, 0.10, ["Humana", "HUMANA", "Humana Inc", "humana", "Humana Medicare Adv", "Humana Gold Plus"]),
    "Kaiser Permanente": (0.04, 0.09, ["Kaiser Permanente", "Kaiser", "KAISER", "Kaiser Foundation HP", "kaiser permanente", "Kaiser Perm"]),
}

# denial category -> [(CARC code, canonical reason text), ...]
DENIALS = {
    "Eligibility": [
        ("CO-27", "Expenses incurred after coverage terminated"),
        ("CO-26", "Expenses incurred prior to coverage"),
        ("CO-31", "Patient cannot be identified as our insured"),
        ("CO-200", "Expenses incurred during lapse in coverage"),
        ("PR-27", "Expenses incurred after coverage terminated"),
        ("CO-177", "Patient has not met the required eligibility requirements"),
    ],
    "Coding Mismatch": [
        ("CO-4", "Procedure code is inconsistent with the modifier used"),
        ("CO-11", "Diagnosis is inconsistent with the procedure"),
        ("CO-181", "Procedure code was invalid on the date of service"),
        ("CO-182", "Procedure modifier was invalid on the date of service"),
        ("CO-146", "Diagnosis was invalid for the date(s) of service reported"),
    ],
    "Missing Information": [
        ("CO-16", "Claim/service lacks information or has submission/billing error(s)"),
        ("CO-252", "An attachment/other documentation is required to adjudicate this claim"),
        ("CO-226", "Information requested from the billing/rendering provider was not provided"),
    ],
    "Prior Authorization": [
        ("CO-197", "Precertification/authorization/notification absent"),
        ("CO-15", "Authorization number is missing, invalid, or does not apply"),
        ("CO-198", "Precertification/authorization exceeded"),
    ],
    "Medical Necessity": [
        ("CO-50", "Non-covered services: not deemed a medical necessity by the payer"),
        ("CO-167", "This (these) diagnosis(es) is (are) not covered"),
        ("CO-151", "Information submitted does not support this many/frequency of services"),
    ],
    "Timely Filing": [
        ("CO-29", "The time limit for filing has expired"),
    ],
    "Duplicate Claim": [
        ("CO-18", "Exact duplicate claim/service"),
        ("OA-18", "Exact duplicate claim/service"),
    ],
    "Non-Covered Service": [
        ("CO-96", "Non-covered charge(s)"),
        ("PR-204", "Service not covered under the patient's current benefit plan"),
        ("PR-49", "Routine/preventive exam or screening procedure done with a routine exam"),
    ],
    "Other": [
        ("CO-22", "Care may be covered by another payer per coordination of benefits"),
        ("CO-97", "Benefit for this service is included in the payment for another service"),
        ("CO-45", "Charge exceeds fee schedule/maximum allowable"),
        ("CO-B7", "Provider was not certified/eligible to be paid for this procedure"),
    ],
}

# per-payer denial category weights (relative)
MIX = {
    "Medicare": {"Coding Mismatch": 30, "Duplicate Claim": 18, "Missing Information": 14, "Medical Necessity": 12, "Other": 12, "Eligibility": 6, "Timely Filing": 4, "Non-Covered Service": 3, "Prior Authorization": 1},
    "Blue Cross Blue Shield": {"Missing Information": 26, "Coding Mismatch": 20, "Eligibility": 14, "Prior Authorization": 12, "Medical Necessity": 8, "Timely Filing": 7, "Duplicate Claim": 5, "Non-Covered Service": 5, "Other": 3},
    "UnitedHealthcare": {"Prior Authorization": 34, "Medical Necessity": 20, "Coding Mismatch": 14, "Eligibility": 9, "Missing Information": 8, "Timely Filing": 5, "Non-Covered Service": 4, "Duplicate Claim": 3, "Other": 3},
    "Aetna": {"Coding Mismatch": 36, "Missing Information": 16, "Prior Authorization": 12, "Eligibility": 10, "Medical Necessity": 8, "Timely Filing": 6, "Non-Covered Service": 5, "Duplicate Claim": 4, "Other": 3},
    "Medicaid": {"Eligibility": 42, "Prior Authorization": 18, "Missing Information": 12, "Coding Mismatch": 10, "Timely Filing": 8, "Medical Necessity": 4, "Non-Covered Service": 3, "Duplicate Claim": 2, "Other": 1},
    "Cigna": {"Timely Filing": 24, "Coding Mismatch": 22, "Missing Information": 14, "Prior Authorization": 12, "Eligibility": 10, "Medical Necessity": 8, "Non-Covered Service": 5, "Duplicate Claim": 3, "Other": 2},
    "Humana": {"Prior Authorization": 28, "Duplicate Claim": 16, "Coding Mismatch": 14, "Medical Necessity": 14, "Eligibility": 10, "Missing Information": 8, "Timely Filing": 4, "Non-Covered Service": 4, "Other": 2},
    "Kaiser Permanente": {"Non-Covered Service": 32, "Eligibility": 18, "Prior Authorization": 16, "Coding Mismatch": 12, "Missing Information": 8, "Medical Necessity": 6, "Other": 4, "Timely Filing": 2, "Duplicate Claim": 2},
}

# (CPT/HCPCS, service line, min charge, max charge)
CPT = [
    ("99213", "Primary Care", 110, 160), ("99214", "Primary Care", 160, 230), ("99215", "Primary Care", 220, 320),
    ("99203", "Primary Care", 150, 210), ("99204", "Primary Care", 230, 330), ("99395", "Primary Care", 180, 260),
    ("G0439", "Primary Care", 150, 200), ("90686", "Primary Care", 25, 45), ("96372", "Primary Care", 30, 60),
    ("J1100", "Primary Care", 15, 35),
    ("36415", "Laboratory", 10, 20), ("80053", "Laboratory", 40, 80), ("85025", "Laboratory", 25, 50),
    ("93000", "Cardiology", 60, 110), ("93306", "Cardiology", 700, 1100), ("93015", "Cardiology", 300, 480),
    ("71046", "Radiology", 90, 160), ("73030", "Radiology", 80, 140), ("70450", "Radiology", 450, 800),
    ("72148", "Radiology", 900, 1600),
    ("20610", "Orthopedics", 150, 260), ("29881", "Orthopedics", 2800, 4200), ("27447", "Orthopedics", 9000, 14000),
    ("97110", "Physical Therapy", 45, 80), ("97140", "Physical Therapy", 40, 75), ("97161", "Physical Therapy", 120, 180),
    ("45378", "Gastroenterology", 900, 1500), ("43239", "Gastroenterology", 800, 1300),
]
ICD = ["E11.9", "I10", "J06.9", "M54.5", "Z00.00", "E78.5", "K21.9", "F41.1", "M25.511", "N39.0",
       "J45.909", "Z12.31", "G89.29", "R10.9", "E66.9", "M17.11", "I25.10", "K57.30", "Z23", "R07.9"]
PROVIDERS = [
    ("1000000011", "Rivera, A."), ("1000000029", "Chen, M."), ("1000000037", "Okafor, D."),
    ("1000000045", "Patel, S."), ("1000000053", "Nguyen, T."), ("1000000061", "Kowalski, J."),
]

STATUS_VARIANTS = {
    "Paid": ["Paid", "PAID", "paid", "Paid ", "PD"],
    "Denied": ["Denied", "DENIED", "denied", "Rejected", "REJECTED", "Deny"],
    "Pending": ["Pending", "PENDING", "In Process", "in process", "Submitted"],
}
APPEAL_VARIANTS = {
    "Not Appealed": ["Not Appealed", "not appealed", "None", "N/A"],
    "Appealed - Pending": ["Appealed - Pending", "Appeal Pending", "APPEALED-PENDING"],
    "Appealed - Overturned": ["Appealed - Overturned", "Overturned", "appeal won"],
    "Appealed - Upheld": ["Appealed - Upheld", "Upheld", "appeal lost"],
}


def weighted_choice(weights):
    keys = list(weights.keys())
    return random.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def messy_date(d):
    r = random.random()
    if r < 0.60:
        return d.isoformat()
    if r < 0.85:
        return d.strftime("%m/%d/%Y")
    if r < 0.95:
        return d.strftime("%d-%b-%Y")
    return d.strftime("%Y%m%d")


def messy_amount(a):
    r = random.random()
    if r < 0.55:
        return "%.2f" % a
    if r < 0.80:
        return "${:,.2f}".format(a)
    if r < 0.92:
        return "{:,.2f}".format(a)
    return str(int(round(a)))


def messy_code(code):
    grp, num = code.split("-")
    r = random.random()
    if r < 0.55:
        return code
    if r < 0.70:
        return grp + num
    if r < 0.80:
        return code.lower()
    if r < 0.88:
        return "%s %s" % (grp, num)
    if r < 0.95:
        return num  # group dropped entirely
    return "%s-%s" % (grp, num.zfill(3)) if num.isdigit() else code


def messy_reason(text):
    r = random.random()
    if r < 0.70:
        return text
    if r < 0.85:
        return text.upper()
    if r < 0.95:
        return text[:40].rstrip() + "..."
    return ""


def messy_cpt(code):
    r = random.random()
    if r < 0.92:
        return code
    if r < 0.96:
        return code.lower()
    return " " + code + " "


def messy_icd(code):
    r = random.random()
    if r < 0.92:
        return code
    if r < 0.96:
        return code.replace(".", "")
    return code.lower()


def rand_date(a, b):
    return a + timedelta(days=random.randint(0, (b - a).days))


def make_claim(idx):
    payer = weighted_choice({k: v[0] for k, v in PAYERS.items()})
    _, base_rate, aliases = PAYERS[payer]
    service_date = rand_date(START, END)

    p_deny = base_rate
    mix = dict(MIX[payer])
    # Story 1: UnitedHealthcare tightened prior-auth rules in March 2026.
    if payer == "UnitedHealthcare" and service_date >= date(2026, 3, 1):
        p_deny += 0.07
        mix["Prior Authorization"] = int(mix["Prior Authorization"] * 1.9)
    # Story 2: Medicaid annual redetermination lapses spike in Jan-Feb.
    if payer == "Medicaid" and service_date.month in (1, 2):
        p_deny += 0.06
        mix["Eligibility"] = int(mix["Eligibility"] * 1.5)

    cpt, service_line, lo, hi = random.choice(CPT)
    amount = random.uniform(lo, hi)
    npi, provider = random.choice(PROVIDERS)

    r = random.random()
    if r < 0.06:
        status = "Pending"
    elif r < 0.06 + p_deny:
        status = "Denied"
    else:
        status = "Paid"

    denial_code = ""
    denial_reason = ""
    appeal = ""
    lag = random.randint(1, 40)
    if status == "Denied":
        category = weighted_choice(mix)
        code, reason = random.choice(DENIALS[category])
        if category == "Timely Filing":
            lag = random.randint(95, 190)
        denial_code = messy_code(code)
        denial_reason = messy_reason(reason)
        appeal_key = weighted_choice({"Not Appealed": 55, "Appealed - Pending": 15,
                                      "Appealed - Overturned": 18, "Appealed - Upheld": 12})
        appeal = random.choice(APPEAL_VARIANTS[appeal_key])
    submission_date = service_date + timedelta(days=lag)

    return {
        "claim_id": "CLM-%06d" % idx,
        "patient_id": "PT-%05d" % random.randint(1, 1800),
        "payer": random.choice(aliases),
        "service_line": service_line,
        "rendering_provider": provider,
        "provider_npi": npi,
        "service_date": messy_date(service_date),
        "submission_date": messy_date(submission_date),
        "cpt_code": messy_cpt(cpt),
        "icd10_code": messy_icd(random.choice(ICD)),
        "billed_amount": messy_amount(amount),
        "claim_status": random.choice(STATUS_VARIANTS[status]),
        "denial_code": denial_code,
        "denial_reason": denial_reason,
        "appeal_status": appeal,
        # helpers for noise injection; dropped before writing
        "_status": status,
        "_submission": submission_date,
        "_amount": amount,
    }


def main():
    random.seed(SEED)
    rows = [make_claim(i + 1) for i in range(N_CLAIMS)]

    # --- noise: resubmissions (same claim_id, later submission, maybe new outcome)
    denied = [r for r in rows if r["_status"] == "Denied"]
    for r in random.sample(denied, int(len(denied) * 0.12)):
        dup = dict(r)
        new_sub = r["_submission"] + timedelta(days=random.randint(20, 45))
        dup["submission_date"] = messy_date(new_sub)
        dup["_submission"] = new_sub
        if random.random() < 0.6:
            dup["claim_status"] = random.choice(STATUS_VARIANTS["Paid"])
            dup["denial_code"] = ""
            dup["denial_reason"] = ""
            dup["appeal_status"] = ""
            dup["_status"] = "Paid"
        rows.append(dup)

    # --- noise: exact duplicate rows
    for r in random.sample(rows, int(N_CLAIMS * 0.03)):
        rows.append(dict(r))

    # --- noise: test records
    for i in range(20):
        t = make_claim(9000 + i)
        t["claim_id"] = "TST-%03d" % i
        t["patient_id"] = "TEST-%03d" % i
        rows.append(t)

    # --- noise: blank / unknown payers
    for r in random.sample(rows, int(N_CLAIMS * 0.012)):
        r["payer"] = random.choice(["", "UNKNOWN", "N/A", "  "])

    # --- noise: invalid amounts
    for r in random.sample(rows, int(N_CLAIMS * 0.01)):
        r["billed_amount"] = random.choice(["", "N/A", "-%.2f" % r["_amount"], "0.00", "#REF!"])

    # --- noise: blank statuses
    for r in random.sample(rows, int(N_CLAIMS * 0.015)):
        r["claim_status"] = random.choice(["", " ", "NULL"])

    # --- noise: a few paid claims that still carry a stale denial code
    for r in random.sample([r for r in rows if r["_status"] == "Paid"], 15):
        r["denial_code"] = messy_code("CO-16")
        r["denial_reason"] = "Claim/service lacks information or has submission/billing error(s)"

    random.shuffle(rows)

    fields = ["claim_id", "patient_id", "payer", "service_line", "rendering_provider", "provider_npi",
              "service_date", "submission_date", "cpt_code", "icd10_code", "billed_amount",
              "claim_status", "denial_code", "denial_reason", "appeal_status"]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in fields})
    print("wrote %d raw rows -> %s" % (len(rows), os.path.relpath(OUT)))


if __name__ == "__main__":
    main()
