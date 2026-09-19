"""Practice drills for the SQL Lab: dozens of distinct questions per lesson.

Hand-writing hundreds of questions does not scale, so each lesson has a set of
question TEMPLATES. A template picks its own parameters from the live data
(a payer, an account, a dollar threshold, a month, a denial code) and produces
one Drill: the question in English, a solution query, two hints, and, when the
question asks for an order, which column the checker should verify is sorted.

generate_set() draws from the templates for one or more lessons, rejects
questions whose answer is empty or huge, removes duplicates, and returns a
reproducible test for a given seed. Nothing here depends on Streamlit.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from . import sql_lab

CLAIM_COLS = ["claim_id", "account_name", "payer", "claim_submission_date", "billed_amount",
              "claim_status", "denial_code", "submission_count"]
CODE_COLS = ["code", "description", "plain_english", "category", "owner"]
AMOUNTS = [250, 500, 1000, 2000, 2500, 5000, 7500, 10000, 15000, 20000]
ALIASES = {"billed_amount": "amount", "payer": "insurer", "account_name": "client",
           "claim_status": "status", "claim_submission_date": "submitted_on"}
LIKE_WORDS = ["authorization", "duplicate", "coverage", "modifier", "medical necessity", "time limit",
              "diagnosis", "bundled", "information"]
DENIED_1_0 = "SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END)"
RATE = "ROUND(100.0 * " + DENIED_1_0 + " / COUNT(*), 1)"
DENIED_DOLLARS = "ROUND(SUM(CASE WHEN claim_status = 'Denied' THEN billed_amount ELSE 0 END), 2)"


@dataclass
class Drill:
    prompt: str
    solution: str
    hints: list
    sort_key: Optional[tuple] = None
    lesson: str = ""
    template: str = ""

    def to_dict(self):
        return {"prompt": self.prompt, "solution": self.solution, "hints": list(self.hints),
                "sort_key": list(self.sort_key) if self.sort_key else None,
                "lesson": self.lesson, "template": self.template}


@dataclass
class Ctx:
    con: object
    payers: list
    accounts: list
    codes: list
    months: list
    categories: list
    owners: list
    first_date: str
    last_date: str
    rows: dict = field(default_factory=dict)


def build_context(con) -> Ctx:
    q = lambda sql: [r[0] for r in con.execute(sql).fetchall()]
    first, last = con.execute("SELECT MIN(claim_submission_date), MAX(claim_submission_date) FROM claims").fetchone()
    return Ctx(
        con=con,
        payers=q("SELECT DISTINCT payer FROM claims ORDER BY 1"),
        accounts=q("SELECT DISTINCT account_name FROM claims ORDER BY 1"),
        codes=q("SELECT denial_code FROM claims WHERE claim_status = 'Denied' GROUP BY denial_code HAVING COUNT(*) >= 8 ORDER BY 1"),
        months=q("SELECT DISTINCT strftime('%Y-%m', claim_submission_date) FROM claims ORDER BY 1"),
        categories=q("SELECT DISTINCT category FROM denial_codes ORDER BY 1"),
        owners=q("SELECT DISTINCT owner FROM denial_codes ORDER BY 1"),
        first_date=first, last_date=last,
    )


# ---------------------------------------------------------------- small helpers
def _pick(rng, xs):
    return xs[rng.randrange(len(xs))]


def _two(rng, xs):
    return rng.sample(xs, 2)


def _money(v) -> str:
    return "${:,}".format(v)


def _dim(rng):
    """A grouping column and the word for it in prose."""
    return _pick(rng, [("payer", "payer"), ("account_name", "account")])


def _values(ctx, col):
    return ctx.payers if col == "payer" else ctx.accounts


def _next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return "%04d-%02d" % ((y + 1, 1) if m == 12 else (y, m + 1))


def _month_name(ym: str) -> str:
    return pd.Timestamp(ym + "-01").strftime("%B %Y")


def _quantile_threshold(ctx, sql_values, rng, lo=0.3, hi=0.7):
    """A threshold that splits the values from `sql_values` somewhere in the middle, so HAVING keeps some groups."""
    vals = sorted(float(r[0]) for r in ctx.con.execute(sql_values).fetchall())
    if len(vals) < 2:
        return None
    k = int(len(vals) * rng.uniform(lo, hi))
    k = max(1, min(len(vals) - 1, k))
    return vals[k]


TEMPLATES = {}


def template(lesson):
    def deco(fn):
        TEMPLATES.setdefault(lesson, []).append(fn)
        return fn
    return deco


# ================================================================ select
@template("select")
def sel_cols(rng, ctx):
    k = _pick(rng, [2, 3, 4])
    chosen = set(rng.sample(CLAIM_COLS, k))
    cols = [c for c in CLAIM_COLS if c in chosen]
    n = _pick(rng, [3, 5, 8, 10, 15])
    return Drill("Show **{}** for the first **{}** claims in the table.".format(", ".join(cols), n),
                 "SELECT {}\nFROM claims\nLIMIT {};".format(", ".join(cols), n),
                 ["List the column names after SELECT, separated by commas.",
                  "SELECT {} FROM claims LIMIT {}".format(", ".join(cols), n)])


@template("select")
def sel_all_codes(rng, ctx):
    n = _pick(rng, [3, 5, 6, 11])
    return Drill("Show **every column** of the first **{}** rows of the **denial_codes** table.".format(n),
                 "SELECT *\nFROM denial_codes\nLIMIT {};".format(n),
                 ["The star * means every column.", "SELECT * FROM denial_codes LIMIT {}".format(n)])


@template("select")
def sel_code_cols(rng, ctx):
    chosen = set(rng.sample(CODE_COLS, _pick(rng, [2, 3])))
    cols = [c for c in CODE_COLS if c in chosen]
    n = _pick(rng, [4, 5, 8, 11])
    return Drill("From **denial_codes**, show **{}** for the first **{}** rows.".format(", ".join(cols), n),
                 "SELECT {}\nFROM denial_codes\nLIMIT {};".format(", ".join(cols), n),
                 ["The table is denial_codes, not claims.", "SELECT {} FROM denial_codes LIMIT {}".format(", ".join(cols), n)])


@template("select")
def sel_distinct(rng, ctx):
    col = _pick(rng, ["payer", "account_name", "claim_status", "submission_count"])
    return Drill("List each **distinct value of {}** in claims, one row per value.".format(col),
                 "SELECT DISTINCT {}\nFROM claims;".format(col),
                 ["DISTINCT removes duplicate rows from the result.", "SELECT DISTINCT {} FROM claims".format(col)])


@template("select")
def sel_alias(rng, ctx):
    col = _pick(rng, list(ALIASES))
    n = _pick(rng, [5, 8, 10])
    return Drill("Show **claim_id** and **{}** for the first **{}** claims, but name the second column **{}** using AS.".format(col, n, ALIASES[col]),
                 "SELECT claim_id, {} AS {}\nFROM claims\nLIMIT {};".format(col, ALIASES[col], n),
                 ["AS renames a column in the result: billed_amount AS amount.",
                  "SELECT claim_id, {} AS {} FROM claims LIMIT {}".format(col, ALIASES[col], n)])


# ================================================================ where
@template("where")
def w_denied_payer(rng, ctx):
    p = _pick(rng, ctx.payers)
    return Drill("List **claim_id, account_name, billed_amount** of every **denied** claim for **{}**.".format(p),
                 "SELECT claim_id, account_name, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND payer = '{}';".format(p),
                 ["Two tests joined with AND: the status and the payer.",
                  "WHERE claim_status = 'Denied' AND payer = '{}'".format(p)])


@template("where")
def w_paid_big(rng, ctx):
    p = _pick(rng, ctx.payers)
    t = _pick(rng, [10000, 15000, 20000])
    return Drill("List **claim_id, account_name, billed_amount** of **paid** claims for **{}** billed **above {}**.".format(p, _money(t)),
                 "SELECT claim_id, account_name, billed_amount\nFROM claims\nWHERE claim_status = 'Paid'\n  AND payer = '{}'\n  AND billed_amount > {};".format(p, t),
                 ["Three tests: status, payer and amount.", "WHERE claim_status = 'Paid' AND payer = '{}' AND billed_amount > {}".format(p, t)])


@template("where")
def w_amount_op(rng, ctx):
    op, word, t = _pick(rng, [(">", "above", _pick(rng, [5000, 7500, 10000, 15000])),
                              (">=", "of at least", _pick(rng, [5000, 10000, 15000])),
                              ("<", "below", _pick(rng, [250, 300, 400])),
                              ("<=", "of at most", _pick(rng, [250, 300, 400]))])
    return Drill("List **claim_id, payer, billed_amount** of **denied** claims billed **{} {}**.".format(word, _money(t)),
                 "SELECT claim_id, payer, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND billed_amount {} {};".format(op, t),
                 ["Numbers are compared without quotes.", "WHERE claim_status = 'Denied' AND billed_amount {} {}".format(op, t)])


@template("where")
def w_between(rng, ctx):
    a, b = _pick(rng, [(5000, 7500), (7500, 10000), (10000, 15000), (2000, 3000), (15000, 25000)])
    return Drill("List **claim_id, payer, billed_amount** of **denied** claims billed **between {} and {}** (inclusive).".format(_money(a), _money(b)),
                 "SELECT claim_id, payer, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND billed_amount BETWEEN {} AND {};".format(a, b),
                 ["BETWEEN a AND b is inclusive at both ends; billed_amount >= a AND billed_amount <= b also works.",
                  "WHERE claim_status = 'Denied' AND billed_amount BETWEEN {} AND {}".format(a, b)])


@template("where")
def w_account_payer(rng, ctx):
    a, p = _pick(rng, ctx.accounts), _pick(rng, ctx.payers)
    return Drill("List **claim_id, billed_amount, denial_code** of **denied** claims for account **{}** with payer **{}**.".format(a, p),
                 "SELECT claim_id, billed_amount, denial_code\nFROM claims\nWHERE claim_status = 'Denied'\n  AND account_name = '{}'\n  AND payer = '{}';".format(a, p),
                 ["Three equality tests joined with AND.", "WHERE claim_status = 'Denied' AND account_name = '{}' AND payer = '{}'".format(a, p)])


@template("where")
def w_or(rng, ctx):
    p1, p2 = _two(rng, ctx.payers)
    t = _pick(rng, [2500, 5000, 10000])
    return Drill("List **claim_id, payer, billed_amount** of **denied** claims billed above **{}** whose payer is **{} or {}**.".format(_money(t), p1, p2),
                 "SELECT claim_id, payer, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND billed_amount > {}\n  AND (payer = '{}' OR payer = '{}');".format(t, p1, p2),
                 ["Put the OR inside parentheses so it does not swallow the AND tests. payer IN ('a', 'b') also works.",
                  "WHERE claim_status = 'Denied' AND billed_amount > {} AND (payer = '{}' OR payer = '{}')".format(t, p1, p2)])


@template("where")
def w_not(rng, ctx):
    a, p = _pick(rng, ctx.accounts), _pick(rng, ctx.payers)
    return Drill("List **claim_id, payer, billed_amount** of **denied** claims for **{}** whose payer is **not {}**.".format(a, p),
                 "SELECT claim_id, payer, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND account_name = '{}'\n  AND payer <> '{}';".format(a, p),
                 ["Not equal is <> (or !=).", "WHERE claim_status = 'Denied' AND account_name = '{}' AND payer <> '{}'".format(a, p)])


@template("where")
def w_date(rng, ctx):
    ym = _pick(rng, ctx.months[1:])
    d = ym + "-01"
    a = _pick(rng, ctx.accounts)
    return Drill("List **claim_id, claim_submission_date, billed_amount** of **denied** claims for **{}** submitted **on or after {}**.".format(a, d),
                 "SELECT claim_id, claim_submission_date, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND account_name = '{}'\n  AND claim_submission_date >= '{}';".format(a, d),
                 ["Dates are text in YYYY-MM-DD form, so >= '{}' works and needs quotes.".format(d),
                  "WHERE claim_status = 'Denied' AND account_name = '{}' AND claim_submission_date >= '{}'".format(a, d)])


@template("where")
def w_code(rng, ctx):
    c = _pick(rng, ctx.codes)
    return Drill("List **claim_id, payer, billed_amount** of claims with denial code **{}**.".format(c),
                 "SELECT claim_id, payer, billed_amount\nFROM claims\nWHERE denial_code = '{}';".format(c),
                 ["The cleaned code lives in denial_code (not denial_reason_code_raw).", "WHERE denial_code = '{}'".format(c)])


@template("where")
def w_rework(rng, ctx):
    p = _pick(rng, ctx.payers)
    t = _pick(rng, [5000, 7500, 10000])
    return Drill("List **claim_id, account_name, billed_amount** of **paid** claims for **{}** that went through rework (**submission_count = 2**) and were billed above **{}**.".format(p, _money(t)),
                 "SELECT claim_id, account_name, billed_amount\nFROM claims\nWHERE claim_status = 'Paid'\n  AND payer = '{}'\n  AND submission_count = 2\n  AND billed_amount > {};".format(p, t),
                 ["Four tests joined with AND.", "WHERE claim_status = 'Paid' AND payer = '{}' AND submission_count = 2 AND billed_amount > {}".format(p, t)])


@template("where")
def w_like(rng, ctx):
    w = _pick(rng, LIKE_WORDS)
    return Drill("List **claim_id, denial_code, denial_reason_description** of **denied** claims whose description contains the word **'{}'**.".format(w),
                 "SELECT claim_id, denial_code, denial_reason_description\nFROM claims\nWHERE claim_status = 'Denied'\n  AND denial_reason_description LIKE '%{}%';".format(w),
                 ["LIKE with % wildcards matches text anywhere in the column: LIKE '%word%'.",
                  "WHERE claim_status = 'Denied' AND denial_reason_description LIKE '%{}%'".format(w)])


# ================================================================ order
@template("order")
def o_top_amount(rng, ctx):
    status = _pick(rng, ["Denied", "Denied", "Paid"])
    desc = rng.random() < 0.7
    n = _pick(rng, [5, 10, 15, 20])
    where = "claim_status = '{}'".format(status)
    scope = "{} claims".format(status.lower())
    if rng.random() < 0.6:
        col, word = _dim(rng)
        v = _pick(rng, _values(ctx, col))
        where += "\n  AND {} = '{}'".format(col, v)
        scope += " for {}".format(v)
    return Drill("Show the **{} {} {}** ({} first): claim_id, payer, billed_amount.".format(
                     n, "largest" if desc else "smallest", scope, "largest" if desc else "smallest"),
                 "SELECT claim_id, payer, billed_amount\nFROM claims\nWHERE {}\nORDER BY billed_amount {}\nLIMIT {};".format(where, "DESC" if desc else "ASC", n),
                 ["ORDER BY billed_amount {} then LIMIT {}.".format("DESC" if desc else "ASC", n),
                  "WHERE {} ORDER BY billed_amount {} LIMIT {}".format(where.replace("\n  ", " "), "DESC" if desc else "ASC", n)],
                 sort_key=("billed_amount", desc))


@template("order")
def o_single(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    return Drill("Show the **single most expensive denied claim** for {} **{}**: claim_id, payer, account_name, billed_amount.".format(word, v),
                 "SELECT claim_id, payer, account_name, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND {} = '{}'\nORDER BY billed_amount DESC\nLIMIT 1;".format(col, v),
                 ["Sort largest first, then keep one row.", "ORDER BY billed_amount DESC LIMIT 1"],
                 sort_key=("billed_amount", True))


@template("order")
def o_two_keys(rng, ctx):
    p = _pick(rng, ctx.payers)
    return Drill("List all **denied** claims for **{}** as claim_id, account_name, billed_amount, sorted by **account_name A to Z, then billed_amount largest first**.".format(p),
                 "SELECT claim_id, account_name, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND payer = '{}'\nORDER BY account_name ASC, billed_amount DESC;".format(p),
                 ["Two sort keys separated by a comma, each with its own direction.", "ORDER BY account_name ASC, billed_amount DESC"],
                 sort_key=("account_name", False))


@template("order")
def o_recent(rng, ctx):
    p = _pick(rng, ctx.payers)
    n = _pick(rng, [5, 10])
    newest = rng.random() < 0.6
    return Drill("Show the **{} {} submitted denied claims** for **{}**: claim_id, claim_submission_date, billed_amount. {} first; break ties by claim_id.".format(
                     n, "most recently" if newest else "earliest", p, "Newest" if newest else "Oldest"),
                 "SELECT claim_id, claim_submission_date, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND payer = '{}'\nORDER BY claim_submission_date {}, claim_id\nLIMIT {};".format(p, "DESC" if newest else "ASC", n),
                 ["Dates sort as text because they are YYYY-MM-DD.", "ORDER BY claim_submission_date {}, claim_id LIMIT {}".format("DESC" if newest else "ASC", n)],
                 sort_key=("claim_submission_date", newest))


@template("order")
def o_code_sorted(rng, ctx):
    c = _pick(rng, ctx.codes)
    return Drill("List **claim_id, payer, billed_amount** of all claims with denial code **{}**, **smallest amount first**.".format(c),
                 "SELECT claim_id, payer, billed_amount\nFROM claims\nWHERE denial_code = '{}'\nORDER BY billed_amount ASC;".format(c),
                 ["ASC is the default direction.", "WHERE denial_code = '{}' ORDER BY billed_amount".format(c)],
                 sort_key=("billed_amount", False))


# ================================================================ aggregate
@template("aggregate")
def a_count(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    status = _pick(rng, ["Denied", "Paid"])
    return Drill("How many **{} claims** does {} **{}** have? Return one column named **total_claims**.".format(status.lower(), word, v),
                 "SELECT COUNT(*) AS total_claims\nFROM claims\nWHERE claim_status = '{}'\n  AND {} = '{}';".format(status, col, v),
                 ["COUNT(*) counts the rows that survive WHERE.", "SELECT COUNT(*) AS total_claims FROM claims WHERE claim_status = '{}' AND {} = '{}'".format(status, col, v)])


@template("aggregate")
def a_sum(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    return Drill("What is the **total billed amount of denied claims** for {} **{}**? One column, **revenue_at_risk**, rounded to 2 decimals.".format(word, v),
                 "SELECT ROUND(SUM(billed_amount), 2) AS revenue_at_risk\nFROM claims\nWHERE claim_status = 'Denied'\n  AND {} = '{}';".format(col, v),
                 ["SUM adds a column up; wrap it in ROUND(..., 2).", "SELECT ROUND(SUM(billed_amount), 2) AS revenue_at_risk FROM claims WHERE ..."])


@template("aggregate")
def a_avg(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    status = _pick(rng, ["Denied", "Paid"])
    return Drill("What is the **average billed amount** of **{}** claims for {} **{}**? One column, **avg_amount**, 2 decimals.".format(status.lower(), word, v),
                 "SELECT ROUND(AVG(billed_amount), 2) AS avg_amount\nFROM claims\nWHERE claim_status = '{}'\n  AND {} = '{}';".format(status, col, v),
                 ["AVG averages the surviving rows.", "SELECT ROUND(AVG(billed_amount), 2) AS avg_amount FROM claims WHERE ..."])


@template("aggregate")
def a_minmax(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    return Drill("For {} **{}**, return the **smallest and largest denied claim amounts** as **min_amount, max_amount**.".format(word, v),
                 "SELECT MIN(billed_amount) AS min_amount,\n       MAX(billed_amount) AS max_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND {} = '{}';".format(col, v),
                 ["MIN and MAX are aggregates too.", "SELECT MIN(billed_amount) AS min_amount, MAX(billed_amount) AS max_amount FROM claims WHERE ..."])


@template("aggregate")
def a_trio(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    return Drill("For **denied** claims of {} **{}**: **denied_claims** (count), **revenue_at_risk** (sum, 2 decimals) and **avg_amount** (average, 2 decimals).".format(word, v),
                 "SELECT COUNT(*) AS denied_claims,\n       ROUND(SUM(billed_amount), 2) AS revenue_at_risk,\n       ROUND(AVG(billed_amount), 2) AS avg_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND {} = '{}';".format(col, v),
                 ["Three aggregates in one SELECT, each with AS.", "SELECT COUNT(*) AS ..., ROUND(SUM(billed_amount), 2) AS ..., ROUND(AVG(billed_amount), 2) AS ... FROM claims WHERE ..."])


@template("aggregate")
def a_count_distinct(rng, ctx):
    c = _pick(rng, ctx.codes)
    col, word = _dim(rng)
    return Drill("How many **different {}s** have at least one claim with denial code **{}**? One column, **n_{}s**.".format(word, c, word),
                 "SELECT COUNT(DISTINCT {}) AS n_{}s\nFROM claims\nWHERE denial_code = '{}';".format(col, word, c),
                 ["COUNT(DISTINCT column) counts unique values instead of rows.", "SELECT COUNT(DISTINCT {}) AS n_{}s FROM claims WHERE denial_code = '{}'".format(col, word, c)])


@template("aggregate")
def a_month_count(rng, ctx):
    ym = _pick(rng, ctx.months)
    status = _pick(rng, ["Denied", None])
    where = "claim_submission_date >= '{}-01'\n  AND claim_submission_date < '{}-01'".format(ym, _next_month(ym))
    if status:
        where = "claim_status = 'Denied'\n  AND " + where
    return Drill("How many {}claims were **submitted in {}**? One column, **n_claims**.".format("**denied** " if status else "", _month_name(ym)),
                 "SELECT COUNT(*) AS n_claims\nFROM claims\nWHERE {};".format(where),
                 ["A month is a date range: from the 1st up to (not including) the 1st of the next month.",
                  "WHERE claim_submission_date >= '{}-01' AND claim_submission_date < '{}-01'".format(ym, _next_month(ym))])


@template("aggregate")
def a_rework(rng, ctx):
    p = _pick(rng, ctx.payers)
    return Drill("How many **{}** claims went through **rework** (submission_count = 2)? One column, **rework_claims**.".format(p),
                 "SELECT COUNT(*) AS rework_claims\nFROM claims\nWHERE payer = '{}'\n  AND submission_count = 2;".format(p),
                 ["Rework is submission_count = 2, regardless of status.", "SELECT COUNT(*) AS rework_claims FROM claims WHERE payer = '{}' AND submission_count = 2".format(p)])


# ================================================================ groupby
def _other_filter(rng, ctx, col, chance=0.5):
    """Sometimes narrow a per-dimension question to one value of the other dimension."""
    other = "account_name" if col == "payer" else "payer"
    if rng.random() < chance:
        v = _pick(rng, _values(ctx, other))
        return "\n  AND {} = '{}'".format(other, v), " for **{}**".format(v)
    return "", ""


@template("groupby")
def g_count_by_dim(rng, ctx):
    col, word = _dim(rng)
    status = _pick(rng, ["Denied", "Paid"])
    extra, scope = _other_filter(rng, ctx, col)
    return Drill("Count **{} claims per {}**{}: {}, **n_claims**; most claims first.".format(status.lower(), word, scope, col),
                 "SELECT {},\n       COUNT(*) AS n_claims\nFROM claims\nWHERE claim_status = '{}'{}\nGROUP BY {}\nORDER BY n_claims DESC;".format(col, status, extra, col),
                 ["The grouping column appears in SELECT and in GROUP BY.", "GROUP BY {} ORDER BY n_claims DESC".format(col)],
                 sort_key=("n_claims", True))


@template("groupby")
def g_sum_by_dim(rng, ctx):
    col, word = _dim(rng)
    extra, scope = _other_filter(rng, ctx, col)
    return Drill("**Revenue at risk per {}**{}: {}, **revenue_at_risk** (sum of denied billed_amount, 2 decimals); largest first.".format(word, scope, col),
                 "SELECT {},\n       ROUND(SUM(billed_amount), 2) AS revenue_at_risk\nFROM claims\nWHERE claim_status = 'Denied'{}\nGROUP BY {}\nORDER BY revenue_at_risk DESC;".format(col, extra, col),
                 ["Filter to denied rows in WHERE, then SUM per group.", "WHERE claim_status = 'Denied' GROUP BY {} ORDER BY revenue_at_risk DESC".format(col)],
                 sort_key=("revenue_at_risk", True))


@template("groupby")
def g_avg_by_dim(rng, ctx):
    col, word = _dim(rng)
    status = _pick(rng, ["Denied", "Paid"])
    extra, scope = _other_filter(rng, ctx, col)
    return Drill("**Average {} claim amount per {}**{}: {}, **avg_amount** (2 decimals); highest first.".format(status.lower(), word, scope, col),
                 "SELECT {},\n       ROUND(AVG(billed_amount), 2) AS avg_amount\nFROM claims\nWHERE claim_status = '{}'{}\nGROUP BY {}\nORDER BY avg_amount DESC;".format(col, status, extra, col),
                 ["AVG per group works like SUM per group.", "GROUP BY {} ORDER BY avg_amount DESC".format(col)],
                 sort_key=("avg_amount", True))


@template("groupby")
def g_by_code(rng, ctx):
    return Drill("Count **denied claims per denial code**: denial_code, **denied_claims**; most common first.",
                 "SELECT denial_code,\n       COUNT(*) AS denied_claims\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY denial_code\nORDER BY denied_claims DESC;",
                 ["Group by the code column; filter to denied so the empty code of paid claims does not appear.",
                  "WHERE claim_status = 'Denied' GROUP BY denial_code ORDER BY denied_claims DESC"],
                 sort_key=("denied_claims", True))


@template("groupby")
def g_two_dims(rng, ctx):
    status = _pick(rng, ["Denied", "Paid"])
    return Drill("Count **{} claims per account and payer**: account_name, payer, **n_claims**.".format(status.lower()),
                 "SELECT account_name, payer,\n       COUNT(*) AS n_claims\nFROM claims\nWHERE claim_status = '{}'\nGROUP BY account_name, payer;".format(status),
                 ["Two grouping columns, both listed in SELECT and GROUP BY.", "GROUP BY account_name, payer"])


@template("groupby")
def g_rework_by_dim(rng, ctx):
    col, word = _dim(rng)
    return Drill("Count **rework claims (submission_count = 2) per {}**: {}, **rework_claims**; most first.".format(word, col),
                 "SELECT {},\n       COUNT(*) AS rework_claims\nFROM claims\nWHERE submission_count = 2\nGROUP BY {}\nORDER BY rework_claims DESC;".format(col, col),
                 ["Filter on submission_count in WHERE.", "WHERE submission_count = 2 GROUP BY {} ORDER BY rework_claims DESC".format(col)],
                 sort_key=("rework_claims", True))


@template("groupby")
def g_top_codes_dollars(rng, ctx):
    n = _pick(rng, [3, 5])
    return Drill("The **{} denial codes with the most denied dollars**: denial_code, **denied_dollars** (2 decimals), largest first.".format(n),
                 "SELECT denial_code,\n       ROUND(SUM(billed_amount), 2) AS denied_dollars\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY denial_code\nORDER BY denied_dollars DESC\nLIMIT {};".format(n),
                 ["GROUP BY, then ORDER BY the sum, then LIMIT.", "GROUP BY denial_code ORDER BY denied_dollars DESC LIMIT {}".format(n)],
                 sort_key=("denied_dollars", True))


@template("groupby")
def g_by_status(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    return Drill("For {} **{}**, per **claim_status**: claim_status, **n_claims**, **total_billed** (2 decimals).".format(word, v),
                 "SELECT claim_status,\n       COUNT(*) AS n_claims,\n       ROUND(SUM(billed_amount), 2) AS total_billed\nFROM claims\nWHERE {} = '{}'\nGROUP BY claim_status;".format(col, v),
                 ["Group by claim_status; the WHERE narrows to one {}.".format(word), "WHERE {} = '{}' GROUP BY claim_status".format(col, v)])


# ================================================================ casewhen
@template("casewhen")
def c_rate_by_dim(rng, ctx):
    col, word = _dim(rng)
    other_col = "account_name" if col == "payer" else "payer"
    where = ""
    scope = ""
    if rng.random() < 0.5:
        v = _pick(rng, _values(ctx, other_col))
        where = "WHERE {} = '{}'\n".format(other_col, v)
        scope = " for **{}** only".format(v)
    return Drill("**Denial rate per {}**{}: {}, **total_claims**, **denied_claims**, **denial_rate_pct** (1 decimal); highest rate first.".format(word, scope, col),
                 "SELECT {},\n       COUNT(*) AS total_claims,\n       {} AS denied_claims,\n       {} AS denial_rate_pct\nFROM claims\n{}GROUP BY {}\nORDER BY denial_rate_pct DESC;".format(col, DENIED_1_0, RATE, where, col),
                 ["Count denied rows with SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END); do not filter them in WHERE.",
                  "ROUND(100.0 * SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) / COUNT(*), 1)"],
                 sort_key=("denial_rate_pct", True))


@template("casewhen")
def c_rate_single(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    return Drill("For {} **{}**: **total_claims**, **denied_claims** and **denial_rate_pct** (1 decimal), in one row.".format(word, v),
                 "SELECT COUNT(*) AS total_claims,\n       {} AS denied_claims,\n       {} AS denial_rate_pct\nFROM claims\nWHERE {} = '{}';".format(DENIED_1_0, RATE, col, v),
                 ["No GROUP BY: one row for one {}. The CASE still does the conditional counting.".format(word),
                  "SELECT COUNT(*) AS total_claims, SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) AS denied_claims, ROUND(100.0 * ... / COUNT(*), 1) AS denial_rate_pct FROM claims WHERE ..."])


@template("casewhen")
def c_paid_denied(rng, ctx):
    col, word = _dim(rng)
    extra, scope = _other_filter(rng, ctx, col)
    where = ("WHERE " + extra.replace("\n  AND ", "") + "\n") if extra else ""
    return Drill("Per **{}**{}, show **paid_claims** and **denied_claims** side by side: {}, paid_claims, denied_claims.".format(word, scope, col),
                 "SELECT {},\n       SUM(CASE WHEN claim_status = 'Paid' THEN 1 ELSE 0 END) AS paid_claims,\n       {} AS denied_claims\nFROM claims\n{}GROUP BY {};".format(col, DENIED_1_0, where, col),
                 ["Two CASE sums, one per status.", "SUM(CASE WHEN claim_status = 'Paid' THEN 1 ELSE 0 END) AS paid_claims, SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) AS denied_claims"])


@template("casewhen")
def c_high_value(rng, ctx):
    col, word = _dim(rng)
    t = _pick(rng, [5000, 10000, 15000])
    extra, scope = _other_filter(rng, ctx, col)
    where = ("WHERE " + extra.replace("\n  AND ", "") + "\n") if extra else ""
    return Drill("Per **{}**{}: {}, **total_claims**, and **high_value_claims** = claims billed above **{}**.".format(word, scope, col, _money(t)),
                 "SELECT {},\n       COUNT(*) AS total_claims,\n       SUM(CASE WHEN billed_amount > {} THEN 1 ELSE 0 END) AS high_value_claims\nFROM claims\n{}GROUP BY {};".format(col, t, where, col),
                 ["The CASE test can be any condition, not just the status.", "SUM(CASE WHEN billed_amount > {} THEN 1 ELSE 0 END) AS high_value_claims".format(t)])


@template("casewhen")
def c_rework_rate(rng, ctx):
    col, word = _dim(rng)
    return Drill("**Rework rate per {}**: {}, **total_claims**, **rework_rate_pct** = share of claims with submission_count = 2 (1 decimal); highest first.".format(word, col),
                 "SELECT {},\n       COUNT(*) AS total_claims,\n       ROUND(100.0 * SUM(CASE WHEN submission_count = 2 THEN 1 ELSE 0 END) / COUNT(*), 1) AS rework_rate_pct\nFROM claims\nGROUP BY {}\nORDER BY rework_rate_pct DESC;".format(col, col),
                 ["Same pattern as the denial rate, with a different CASE test.", "ROUND(100.0 * SUM(CASE WHEN submission_count = 2 THEN 1 ELSE 0 END) / COUNT(*), 1)"],
                 sort_key=("rework_rate_pct", True))


@template("casewhen")
def c_bands(rng, ctx):
    t1, t2 = _pick(rng, [(10000, 1000), (5000, 500), (15000, 2500)])
    return Drill("Put **denied** claims into size bands with CASE: **'High'** if billed_amount >= {}, **'Medium'** if >= {}, else **'Low'**. Return **size_band, denied_claims** (count per band).".format(_money(t1), _money(t2)),
                 "SELECT CASE WHEN billed_amount >= {} THEN 'High'\n            WHEN billed_amount >= {} THEN 'Medium'\n            ELSE 'Low' END AS size_band,\n       COUNT(*) AS denied_claims\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY size_band;".format(t1, t2),
                 ["A CASE can label rows, not only count them; then GROUP BY the label.",
                  "SELECT CASE WHEN billed_amount >= {} THEN 'High' WHEN billed_amount >= {} THEN 'Medium' ELSE 'Low' END AS size_band, COUNT(*) ... GROUP BY size_band".format(t1, t2)])


@template("casewhen")
def c_denied_dollars(rng, ctx):
    col, word = _dim(rng)
    return Drill("Per **{}**: {}, **total_billed** (all claims, 2 decimals) and **revenue_at_risk** (denied claims only, 2 decimals).".format(word, col),
                 "SELECT {},\n       ROUND(SUM(billed_amount), 2) AS total_billed,\n       {} AS revenue_at_risk\nFROM claims\nGROUP BY {};".format(col, DENIED_DOLLARS, col),
                 ["A CASE can return a number instead of 1/0: THEN billed_amount ELSE 0.", "SUM(CASE WHEN claim_status = 'Denied' THEN billed_amount ELSE 0 END)"])


# ================================================================ having
@template("having")
def h_min_count(rng, ctx):
    col, word = _dim(rng)
    k = _quantile_threshold(ctx, "SELECT COUNT(*) FROM claims WHERE claim_status = 'Denied' GROUP BY {}".format(col), rng)
    k = int(k) if k else 20
    op, w = _pick(rng, [(">=", "at least"), (">", "more than")])
    return Drill("Which **{}s have {} {} denied claims**? {}, **denied_claims**.".format(word, w, k, col),
                 "SELECT {},\n       COUNT(*) AS denied_claims\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY {}\nHAVING COUNT(*) {} {};".format(col, col, op, k),
                 ["WHERE keeps denied rows; HAVING keeps big groups.", "GROUP BY {} HAVING COUNT(*) {} {}".format(col, op, k)])


@template("having")
def h_dollars(rng, ctx):
    col, word = _dim(rng)
    t = _quantile_threshold(ctx, "SELECT SUM(billed_amount) FROM claims WHERE claim_status = 'Denied' GROUP BY {}".format(col), rng)
    t = int(round(t / 1000.0)) * 1000 if t else 100000
    return Drill("Which **{}s have more than {} of denied dollars**? {}, **revenue_at_risk** (2 decimals).".format(word, _money(t), col),
                 "SELECT {},\n       ROUND(SUM(billed_amount), 2) AS revenue_at_risk\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY {}\nHAVING SUM(billed_amount) > {};".format(col, col, t),
                 ["HAVING can test a SUM, not only COUNT.", "GROUP BY {} HAVING SUM(billed_amount) > {}".format(col, t)])


@template("having")
def h_rate(rng, ctx):
    col, word = _dim(rng)
    r = _quantile_threshold(ctx, "SELECT 100.0 * {} / COUNT(*) FROM claims GROUP BY {}".format(DENIED_1_0, col), rng)
    r = round(r, 1) if r else 10.0
    return Drill("Which **{}s have a denial rate above {}%**? {}, **total_claims**, **denial_rate_pct** (1 decimal).".format(word, r, col),
                 "SELECT {},\n       COUNT(*) AS total_claims,\n       {} AS denial_rate_pct\nFROM claims\nGROUP BY {}\nHAVING 100.0 * {} / COUNT(*) > {};".format(col, RATE, col, DENIED_1_0, r),
                 ["HAVING can test the rate expression itself (or its alias in SQLite).", "HAVING 100.0 * SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) / COUNT(*) > {}".format(r)])


@template("having")
def h_codes(rng, ctx):
    k = _quantile_threshold(ctx, "SELECT COUNT(*) FROM claims WHERE claim_status = 'Denied' GROUP BY denial_code", rng)
    k = int(k) if k else 30
    return Drill("Which **denial codes appear more than {} times**? denial_code, **denied_claims**; most common first.".format(k),
                 "SELECT denial_code,\n       COUNT(*) AS denied_claims\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY denial_code\nHAVING COUNT(*) > {}\nORDER BY denied_claims DESC;".format(k),
                 ["Filter rows (denied) in WHERE, groups (count) in HAVING.", "GROUP BY denial_code HAVING COUNT(*) > {} ORDER BY denied_claims DESC".format(k)],
                 sort_key=("denied_claims", True))


@template("having")
def h_avg(rng, ctx):
    col, word = _dim(rng)
    t = _quantile_threshold(ctx, "SELECT AVG(billed_amount) FROM claims WHERE claim_status = 'Denied' GROUP BY {}".format(col), rng)
    t = int(round(t / 100.0)) * 100 if t else 1500
    return Drill("Which **{}s have an average denied claim above {}**? {}, **avg_amount** (2 decimals).".format(word, _money(t), col),
                 "SELECT {},\n       ROUND(AVG(billed_amount), 2) AS avg_amount\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY {}\nHAVING AVG(billed_amount) > {};".format(col, col, t),
                 ["HAVING AVG(...) > threshold.", "GROUP BY {} HAVING AVG(billed_amount) > {}".format(col, t)])


@template("having")
def h_two_dims(rng, ctx):
    k = _quantile_threshold(ctx, "SELECT COUNT(*) FROM claims WHERE claim_status = 'Denied' GROUP BY account_name, payer", rng, 0.5, 0.85)
    k = int(k) if k else 20
    return Drill("Which **account and payer combinations have at least {} denied claims**? account_name, payer, **denied_claims**; most first.".format(k),
                 "SELECT account_name, payer,\n       COUNT(*) AS denied_claims\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY account_name, payer\nHAVING COUNT(*) >= {}\nORDER BY denied_claims DESC;".format(k),
                 ["Two grouping columns, then HAVING on the count.", "GROUP BY account_name, payer HAVING COUNT(*) >= {}".format(k)],
                 sort_key=("denied_claims", True))


# ================================================================ dates
@template("dates")
def d_monthly(rng, ctx):
    kind = _pick(rng, ["denied", "dollars", "all"])
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col)) if rng.random() < 0.6 else None
    where = []
    scope = ""
    if v:
        where.append("{} = '{}'".format(col, v))
        scope = " for **{}**".format(v)
    if kind == "denied":
        where.append("claim_status = 'Denied'")
        agg, name, what = "COUNT(*)", "denied_claims", "denied claims"
    elif kind == "dollars":
        where.append("claim_status = 'Denied'")
        agg, name, what = "ROUND(SUM(billed_amount), 2)", "denied_dollars", "denied dollars (2 decimals)"
    else:
        agg, name, what = "COUNT(*)", "n_claims", "claims"
    w = ("WHERE " + "\n  AND ".join(where) + "\n") if where else ""
    return Drill("**{} per month**{}: month (as YYYY-MM), **{}**; oldest month first.".format(what.capitalize(), scope, name),
                 "SELECT strftime('%Y-%m', claim_submission_date) AS month,\n       {} AS {}\nFROM claims\n{}GROUP BY month\nORDER BY month;".format(agg, name, w),
                 ["strftime('%Y-%m', claim_submission_date) turns a date into its month.", "GROUP BY month ORDER BY month"],
                 sort_key=("month", False))


@template("dates")
def d_month_filter(rng, ctx):
    ym = _pick(rng, ctx.months)
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    return Drill("How many **denied claims** did {} **{}** have in **{}**? One column, **denied_claims**.".format(word, v, _month_name(ym)),
                 "SELECT COUNT(*) AS denied_claims\nFROM claims\nWHERE claim_status = 'Denied'\n  AND {} = '{}'\n  AND strftime('%Y-%m', claim_submission_date) = '{}';".format(col, v, ym),
                 ["Compare the month string: strftime('%Y-%m', claim_submission_date) = '{}'.".format(ym),
                  "WHERE claim_status = 'Denied' AND {} = '{}' AND strftime('%Y-%m', claim_submission_date) = '{}'".format(col, v, ym)])


@template("dates")
def d_top_month(rng, ctx):
    most = rng.random() < 0.7
    return Drill("Which **month had the {} denied claims**? month, **denied_claims** (one row).".format("most" if most else "fewest"),
                 "SELECT strftime('%Y-%m', claim_submission_date) AS month,\n       COUNT(*) AS denied_claims\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY month\nORDER BY denied_claims {}\nLIMIT 1;".format("DESC" if most else "ASC"),
                 ["Group by month, sort by the count, keep one row.", "GROUP BY month ORDER BY denied_claims {} LIMIT 1".format("DESC" if most else "ASC")])


@template("dates")
def d_monthly_rate(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    return Drill("**Monthly denial rate for {}**: month, **total_claims**, **denied_claims**, **denial_rate_pct** (1 decimal); oldest first.".format(v),
                 "SELECT strftime('%Y-%m', claim_submission_date) AS month,\n       COUNT(*) AS total_claims,\n       {} AS denied_claims,\n       {} AS denial_rate_pct\nFROM claims\nWHERE {} = '{}'\nGROUP BY month\nORDER BY month;".format(DENIED_1_0, RATE, col, v),
                 ["The CASE WHEN rate pattern, grouped by month.", "GROUP BY month ORDER BY month"],
                 sort_key=("month", False))


@template("dates")
def d_range_count(rng, ctx):
    m1 = _pick(rng, ctx.months[:-1])
    m2 = _pick(rng, [m for m in ctx.months if m > m1])
    d1, d2 = m1 + "-15", m2 + "-14"
    return Drill("How many claims were submitted **between {} and {}** (inclusive)? One column, **n_claims**.".format(d1, d2),
                 "SELECT COUNT(*) AS n_claims\nFROM claims\nWHERE claim_submission_date BETWEEN '{}' AND '{}';".format(d1, d2),
                 ["ISO dates compare correctly as text, so BETWEEN works.", "WHERE claim_submission_date BETWEEN '{}' AND '{}'".format(d1, d2)])


@template("dates")
def d_month_dim(rng, ctx):
    col, word = _dim(rng)
    return Drill("**Denied claims per month and {}**: month, {}, **denied_claims**; ordered by month then {}.".format(word, col, col),
                 "SELECT strftime('%Y-%m', claim_submission_date) AS month,\n       {},\n       COUNT(*) AS denied_claims\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY month, {}\nORDER BY month, {};".format(col, col, col),
                 ["Group by both the month expression and the {} column.".format(word), "GROUP BY month, {} ORDER BY month, {}".format(col, col)],
                 sort_key=("month", False))


# ================================================================ join
@template("join")
def j_category_counts(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col)) if rng.random() < 0.6 else None
    extra = "  AND c.{} = '{}'\n".format(col, v) if v else ""
    scope = " for **{}**".format(v) if v else ""
    return Drill("**Denied claims per root-cause category**{}: category, **denied_claims**; most first.".format(scope),
                 "SELECT d.category,\n       COUNT(*) AS denied_claims\nFROM claims c\nJOIN denial_codes d ON d.code = c.denial_code\nWHERE c.claim_status = 'Denied'\n{}GROUP BY d.category\nORDER BY denied_claims DESC;".format(extra),
                 ["Join on the cleaned code: d.code = c.denial_code.", "FROM claims c JOIN denial_codes d ON d.code = c.denial_code ... GROUP BY d.category"],
                 sort_key=("denied_claims", True))


@template("join")
def j_list(rng, ctx):
    p = _pick(rng, ctx.payers)
    c = _pick(rng, ctx.codes)
    return Drill("For **denied {} claims with code {}**, list **claim_id, denial_code, plain_english** (from denial_codes).".format(p, c),
                 "SELECT c.claim_id, c.denial_code, d.plain_english\nFROM claims c\nJOIN denial_codes d ON d.code = c.denial_code\nWHERE c.claim_status = 'Denied'\n  AND c.payer = '{}'\n  AND c.denial_code = '{}';".format(p, c),
                 ["plain_english lives in denial_codes, so you need the join to show it.", "JOIN denial_codes d ON d.code = c.denial_code WHERE c.payer = '{}' AND c.denial_code = '{}'".format(p, c)])


@template("join")
def j_owner(rng, ctx):
    return Drill("**Denied claims per owner of the fix** (owner column in denial_codes): owner, **denied_claims**, **revenue_at_risk** (2 decimals); most claims first.",
                 "SELECT d.owner,\n       COUNT(*) AS denied_claims,\n       ROUND(SUM(c.billed_amount), 2) AS revenue_at_risk\nFROM claims c\nJOIN denial_codes d ON d.code = c.denial_code\nWHERE c.claim_status = 'Denied'\nGROUP BY d.owner\nORDER BY denied_claims DESC;",
                 ["Group by a column from the joined table.", "GROUP BY d.owner ORDER BY denied_claims DESC"],
                 sort_key=("denied_claims", True))


@template("join")
def j_cat_dim(rng, ctx):
    col, word = _dim(rng)
    return Drill("**Denied claims per category and {}**: category, {}, **denied_claims**.".format(word, col),
                 "SELECT d.category, c.{},\n       COUNT(*) AS denied_claims\nFROM claims c\nJOIN denial_codes d ON d.code = c.denial_code\nWHERE c.claim_status = 'Denied'\nGROUP BY d.category, c.{};".format(col, col),
                 ["Two grouping columns from two tables.", "GROUP BY d.category, c.{}".format(col)])


@template("join")
def j_cat_dollars(rng, ctx):
    return Drill("**Revenue at risk per category**: category, **denied_claims**, **revenue_at_risk** (2 decimals), **avg_amount** (2 decimals); largest revenue first.",
                 "SELECT d.category,\n       COUNT(*) AS denied_claims,\n       ROUND(SUM(c.billed_amount), 2) AS revenue_at_risk,\n       ROUND(AVG(c.billed_amount), 2) AS avg_amount\nFROM claims c\nJOIN denial_codes d ON d.code = c.denial_code\nWHERE c.claim_status = 'Denied'\nGROUP BY d.category\nORDER BY revenue_at_risk DESC;",
                 ["Three aggregates over the joined rows.", "GROUP BY d.category ORDER BY revenue_at_risk DESC"],
                 sort_key=("revenue_at_risk", True))


@template("join")
def j_top_codes_desc(rng, ctx):
    n = _pick(rng, [3, 5])
    return Drill("The **{} most common denial codes with their meaning**: denial_code, **plain_english**, **denied_claims**; most common first.".format(n),
                 "SELECT c.denial_code, d.plain_english,\n       COUNT(*) AS denied_claims\nFROM claims c\nJOIN denial_codes d ON d.code = c.denial_code\nWHERE c.claim_status = 'Denied'\nGROUP BY c.denial_code, d.plain_english\nORDER BY denied_claims DESC\nLIMIT {};".format(n),
                 ["Group by both the code and its description (one description per code, so nothing splits).", "GROUP BY c.denial_code, d.plain_english ORDER BY denied_claims DESC LIMIT {}".format(n)],
                 sort_key=("denied_claims", True))


@template("join")
def j_category_dim_filter(rng, ctx):
    cat = _pick(rng, ctx.categories)
    col, word = _dim(rng)
    return Drill("For the category **{}**, count denied claims per **{}**: {}, **denied_claims**; most first.".format(cat, word, col),
                 "SELECT c.{},\n       COUNT(*) AS denied_claims\nFROM claims c\nJOIN denial_codes d ON d.code = c.denial_code\nWHERE c.claim_status = 'Denied'\n  AND d.category = '{}'\nGROUP BY c.{}\nORDER BY denied_claims DESC;".format(col, cat, col),
                 ["Filter on the joined table's column in WHERE: d.category = '...'.", "WHERE d.category = '{}' GROUP BY c.{}".format(cat, col)],
                 sort_key=("denied_claims", True))


# ================================================================ cte
@template("cte")
def cte_above_rate(rng, ctx):
    col, word = _dim(rng)
    return Drill("Using a CTE named **{}_rates**, list the **{}s whose denial rate is above the overall rate**: {}, **denial_rate_pct** (1 decimal); highest first.".format(word, word, col),
                 "WITH {}_rates AS (\n    SELECT {},\n           {} AS denial_rate_pct\n    FROM claims\n    GROUP BY {}\n)\nSELECT {}, denial_rate_pct\nFROM {}_rates\nWHERE denial_rate_pct > (\n    SELECT 100.0 * {} / COUNT(*) FROM claims\n)\nORDER BY denial_rate_pct DESC;".format(word, col, RATE, col, col, word, DENIED_1_0),
                 ["The CTE holds one row per {}; the subquery in WHERE is the overall rate.".format(word),
                  "WITH {}_rates AS (SELECT {}, <rate> FROM claims GROUP BY {}) SELECT ... WHERE denial_rate_pct > (SELECT <overall rate> FROM claims)".format(word, col, col)],
                 sort_key=("denial_rate_pct", True))


@template("cte")
def cte_max(rng, ctx):
    col, word = _dim(rng)
    return Drill("Using a CTE of **revenue at risk per {}**, return the **{} with the largest revenue at risk**: {}, **revenue_at_risk** (2 decimals).".format(word, word, col),
                 "WITH at_risk AS (\n    SELECT {},\n           ROUND(SUM(billed_amount), 2) AS revenue_at_risk\n    FROM claims\n    WHERE claim_status = 'Denied'\n    GROUP BY {}\n)\nSELECT {}, revenue_at_risk\nFROM at_risk\nWHERE revenue_at_risk = (SELECT MAX(revenue_at_risk) FROM at_risk);".format(col, col, col),
                 ["A CTE can be read twice: once in FROM, once in a subquery. ORDER BY ... DESC LIMIT 1 also works.",
                  "WITH at_risk AS (...) SELECT ... FROM at_risk WHERE revenue_at_risk = (SELECT MAX(revenue_at_risk) FROM at_risk)"])


@template("cte")
def cte_month_above(rng, ctx):
    return Drill("Using a CTE named **monthly**, list the **months whose denial rate is above the overall rate**: month, **denial_rate_pct** (1 decimal); oldest first.",
                 "WITH monthly AS (\n    SELECT strftime('%Y-%m', claim_submission_date) AS month,\n           {} AS denial_rate_pct\n    FROM claims\n    GROUP BY month\n)\nSELECT month, denial_rate_pct\nFROM monthly\nWHERE denial_rate_pct > (\n    SELECT 100.0 * {} / COUNT(*) FROM claims\n)\nORDER BY month;".format(RATE, DENIED_1_0),
                 ["Same shape as the payer version, grouped by month.", "WITH monthly AS (SELECT strftime('%Y-%m', claim_submission_date) AS month, <rate> FROM claims GROUP BY month) SELECT ..."],
                 sort_key=("month", False))


@template("cte")
def cte_two(rng, ctx):
    col, word = _dim(rng)
    return Drill("With **two CTEs**, **totals** (claims per {}) and **denied** (denied claims per {}), join them to return {}, **total_claims**, **denied_claims**, **denial_rate_pct** (1 decimal).".format(word, word, col),
                 "WITH totals AS (\n    SELECT {}, COUNT(*) AS total_claims\n    FROM claims\n    GROUP BY {}\n),\ndenied AS (\n    SELECT {}, COUNT(*) AS denied_claims\n    FROM claims\n    WHERE claim_status = 'Denied'\n    GROUP BY {}\n)\nSELECT t.{}, t.total_claims, d.denied_claims,\n       ROUND(100.0 * d.denied_claims / t.total_claims, 1) AS denial_rate_pct\nFROM totals t\nJOIN denied d ON d.{} = t.{};".format(col, col, col, col, col, col, col),
                 ["Separate CTEs with a comma after the first closing parenthesis; join them on the {} column.".format(word),
                  "WITH totals AS (...), denied AS (...) SELECT ... FROM totals t JOIN denied d ON d.{} = t.{}".format(col, col)])


@template("cte")
def cte_avg_subquery(rng, ctx):
    return Drill("How many **denied claims are billed above the average denied claim amount**? One column, **above_avg_claims**.",
                 "SELECT COUNT(*) AS above_avg_claims\nFROM claims\nWHERE claim_status = 'Denied'\n  AND billed_amount > (\n    SELECT AVG(billed_amount) FROM claims WHERE claim_status = 'Denied'\n);",
                 ["A subquery in WHERE computes the average once.", "WHERE claim_status = 'Denied' AND billed_amount > (SELECT AVG(billed_amount) FROM claims WHERE claim_status = 'Denied')"])


@template("cte")
def cte_share(rng, ctx):
    col, word = _dim(rng)
    return Drill("Using a CTE named **total** for the overall number of denied claims, return each {}'s **share of all denials**: {}, **denied_claims**, **share_pct** (1 decimal); largest first.".format(word, col),
                 "WITH total AS (\n    SELECT COUNT(*) AS all_denied FROM claims WHERE claim_status = 'Denied'\n)\nSELECT c.{},\n       COUNT(*) AS denied_claims,\n       ROUND(100.0 * COUNT(*) / t.all_denied, 1) AS share_pct\nFROM claims c\nCROSS JOIN total t\nWHERE c.claim_status = 'Denied'\nGROUP BY c.{}, t.all_denied\nORDER BY share_pct DESC;".format(col, col),
                 ["A one-row CTE can be CROSS JOINed so every group can divide by it. A subquery (SELECT COUNT(*) ...) in the SELECT list also works.",
                  "WITH total AS (SELECT COUNT(*) AS all_denied FROM claims WHERE claim_status = 'Denied') SELECT c.{}, COUNT(*), ROUND(100.0 * COUNT(*) / t.all_denied, 1) FROM claims c CROSS JOIN total t WHERE ... GROUP BY c.{}, t.all_denied".format(col, col)],
                 sort_key=("share_pct", True))


# ================================================================ window
@template("window")
def w_rank_dim(rng, ctx):
    col, word = _dim(rng)
    metric, name, expr = _pick(rng, [("denial rate", "denial_rate_pct", RATE),
                                     ("revenue at risk", "revenue_at_risk", DENIED_DOLLARS),
                                     ("number of denied claims", "denied_claims", DENIED_1_0)])
    return Drill("**Rank {}s by {}** (1 = highest): {}, **{}**, **rank_no**; ordered by rank.".format(word, metric, col, name),
                 "WITH per_{} AS (\n    SELECT {},\n           {} AS {}\n    FROM claims\n    GROUP BY {}\n)\nSELECT {}, {},\n       RANK() OVER (ORDER BY {} DESC) AS rank_no\nFROM per_{}\nORDER BY rank_no;".format(word, col, expr, name, col, col, name, name, word),
                 ["Aggregate first (a CTE), then RANK() OVER (ORDER BY ... DESC) on the result.", "RANK() OVER (ORDER BY {} DESC) AS rank_no".format(name)],
                 sort_key=("rank_no", False))


@template("window")
def w_partition(rng, ctx):
    metric, name, expr = _pick(rng, [("denied claims", "denied_claims", "COUNT(*)"),
                                     ("denied dollars", "denied_dollars", "ROUND(SUM(billed_amount), 2)")])
    return Drill("**For each account, rank its payers by {}** (1 = most): account_name, payer, **{}**, **rank_in_account**; ordered by account_name then rank.".format(metric, name),
                 "WITH per_pair AS (\n    SELECT account_name, payer,\n           {} AS {}\n    FROM claims\n    WHERE claim_status = 'Denied'\n    GROUP BY account_name, payer\n)\nSELECT account_name, payer, {},\n       RANK() OVER (PARTITION BY account_name ORDER BY {} DESC) AS rank_in_account\nFROM per_pair\nORDER BY account_name, rank_in_account;".format(expr, name, name, name),
                 ["PARTITION BY account_name restarts the ranking for each account.", "RANK() OVER (PARTITION BY account_name ORDER BY {} DESC)".format(name)],
                 sort_key=("account_name", False))


@template("window")
def w_row_number_top(rng, ctx):
    col, word = _dim(rng)
    return Drill("The **most expensive denied claim for each {}**: {}, claim_id, billed_amount. Use ROW_NUMBER() OVER (PARTITION BY ...) and keep row number 1.".format(word, col),
                 "WITH ranked AS (\n    SELECT {}, claim_id, billed_amount,\n           ROW_NUMBER() OVER (PARTITION BY {} ORDER BY billed_amount DESC) AS rn\n    FROM claims\n    WHERE claim_status = 'Denied'\n)\nSELECT {}, claim_id, billed_amount\nFROM ranked\nWHERE rn = 1;".format(col, col, col),
                 ["Window functions cannot go in WHERE directly; compute rn in a CTE, then filter rn = 1 outside.",
                  "WITH ranked AS (SELECT ..., ROW_NUMBER() OVER (PARTITION BY {} ORDER BY billed_amount DESC) AS rn FROM claims WHERE claim_status = 'Denied') SELECT ... FROM ranked WHERE rn = 1".format(col)])


@template("window")
def w_running_total(rng, ctx):
    return Drill("**Running total of denied dollars by month**: month, **denied_dollars** (2 decimals), **running_total** (2 decimals); oldest first.",
                 "WITH monthly AS (\n    SELECT strftime('%Y-%m', claim_submission_date) AS month,\n           ROUND(SUM(billed_amount), 2) AS denied_dollars\n    FROM claims\n    WHERE claim_status = 'Denied'\n    GROUP BY month\n)\nSELECT month, denied_dollars,\n       ROUND(SUM(denied_dollars) OVER (ORDER BY month), 2) AS running_total\nFROM monthly\nORDER BY month;",
                 ["SUM(...) OVER (ORDER BY month) adds up everything up to and including the current row.", "ROUND(SUM(denied_dollars) OVER (ORDER BY month), 2) AS running_total"],
                 sort_key=("month", False))


@template("window")
def w_share_over(rng, ctx):
    col, word = _dim(rng)
    return Drill("Each {}'s **share of all denied claims** using a window total: {}, **denied_claims**, **share_pct** (1 decimal); largest first.".format(word, col),
                 "SELECT {},\n       COUNT(*) AS denied_claims,\n       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS share_pct\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY {}\nORDER BY share_pct DESC;".format(col, col),
                 ["SUM(COUNT(*)) OVER () is the grand total across all groups, available on every row.", "ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS share_pct"],
                 sort_key=("share_pct", True))


@template("window")
def w_lag(rng, ctx):
    return Drill("**Month-over-month change in denied claims**: month, **denied_claims**, **change_vs_prev** (this month minus the previous month; NULL for the first month); oldest first.",
                 "WITH monthly AS (\n    SELECT strftime('%Y-%m', claim_submission_date) AS month,\n           COUNT(*) AS denied_claims\n    FROM claims\n    WHERE claim_status = 'Denied'\n    GROUP BY month\n)\nSELECT month, denied_claims,\n       denied_claims - LAG(denied_claims) OVER (ORDER BY month) AS change_vs_prev\nFROM monthly\nORDER BY month;",
                 ["LAG(column) OVER (ORDER BY month) reads the previous row's value.", "denied_claims - LAG(denied_claims) OVER (ORDER BY month) AS change_vs_prev"],
                 sort_key=("month", False))


# ================================================================ capstone
@template("capstone")
def cap_top_n(rng, ctx):
    col, word = _dim(rng)
    n = _pick(rng, [3, 5])
    k = _pick(rng, [50, 100, 200])
    by, order = _pick(rng, [("denial rate", "denial_rate_pct DESC, revenue_at_risk DESC"), ("revenue at risk", "revenue_at_risk DESC, denial_rate_pct DESC")])
    return Drill("**Top {} {}s by {}**, counting only {}s with at least **{}** claims: {}, **total_claims**, **denied_claims**, **denial_rate_pct** (1 decimal), **revenue_at_risk** (2 decimals).".format(n, word, by, word, k, col),
                 "SELECT {},\n       COUNT(*) AS total_claims,\n       {} AS denied_claims,\n       {} AS denial_rate_pct,\n       {} AS revenue_at_risk\nFROM claims\nGROUP BY {}\nHAVING COUNT(*) >= {}\nORDER BY {}\nLIMIT {};".format(col, DENIED_1_0, RATE, DENIED_DOLLARS, col, k, order, n),
                 ["Four aggregates, HAVING on the count, ORDER BY the metric, LIMIT.", "GROUP BY {} HAVING COUNT(*) >= {} ORDER BY {} LIMIT {}".format(col, k, order, n)],
                 sort_key=(order.split(" ")[0], True))


@template("capstone")
def cap_pairs(rng, ctx):
    n = _pick(rng, [5, 10])
    k = _pick(rng, [30, 50])
    return Drill("**Top {} account and payer combinations by revenue at risk**, with at least **{}** claims each: account_name, payer, **total_claims**, **denied_claims**, **denial_rate_pct** (1 decimal), **revenue_at_risk** (2 decimals).".format(n, k),
                 "SELECT account_name, payer,\n       COUNT(*) AS total_claims,\n       {} AS denied_claims,\n       {} AS denial_rate_pct,\n       {} AS revenue_at_risk\nFROM claims\nGROUP BY account_name, payer\nHAVING COUNT(*) >= {}\nORDER BY revenue_at_risk DESC\nLIMIT {};".format(DENIED_1_0, RATE, DENIED_DOLLARS, k, n),
                 ["Same report, two grouping columns.", "GROUP BY account_name, payer HAVING COUNT(*) >= {} ORDER BY revenue_at_risk DESC LIMIT {}".format(k, n)],
                 sort_key=("revenue_at_risk", True))


@template("capstone")
def cap_window(rng, ctx):
    ym = _pick(rng, ctx.months[1:-1])
    n = _pick(rng, [3, 5])
    return Drill("For claims **submitted from {} onwards**, the **top {} payers by denial rate** with at least **30** claims: payer, **total_claims**, **denied_claims**, **denial_rate_pct** (1 decimal), **revenue_at_risk** (2 decimals).".format(ym + "-01", n),
                 "SELECT payer,\n       COUNT(*) AS total_claims,\n       {} AS denied_claims,\n       {} AS denial_rate_pct,\n       {} AS revenue_at_risk\nFROM claims\nWHERE claim_submission_date >= '{}-01'\nGROUP BY payer\nHAVING COUNT(*) >= 30\nORDER BY denial_rate_pct DESC, revenue_at_risk DESC\nLIMIT {};".format(DENIED_1_0, RATE, DENIED_DOLLARS, ym, n),
                 ["The date window is a WHERE; the size floor is a HAVING.", "WHERE claim_submission_date >= '{}-01' GROUP BY payer HAVING COUNT(*) >= 30 ORDER BY denial_rate_pct DESC, revenue_at_risk DESC LIMIT {}".format(ym, n)],
                 sort_key=("denial_rate_pct", True))


@template("capstone")
def cap_with_avg(rng, ctx):
    col, word = _dim(rng)
    return Drill("A **full {} report**: {}, **total_claims**, **denied_claims**, **denial_rate_pct** (1 decimal), **revenue_at_risk** (2 decimals) and **avg_denied_amount** (average billed_amount of denied claims, 2 decimals); highest rate first.".format(word, col),
                 "SELECT {},\n       COUNT(*) AS total_claims,\n       {} AS denied_claims,\n       {} AS denial_rate_pct,\n       {} AS revenue_at_risk,\n       ROUND(AVG(CASE WHEN claim_status = 'Denied' THEN billed_amount END), 2) AS avg_denied_amount\nFROM claims\nGROUP BY {}\nORDER BY denial_rate_pct DESC;".format(col, DENIED_1_0, RATE, DENIED_DOLLARS, col),
                 ["AVG(CASE WHEN ... THEN billed_amount END) ignores the paid rows because the CASE returns NULL for them.",
                  "ROUND(AVG(CASE WHEN claim_status = 'Denied' THEN billed_amount END), 2) AS avg_denied_amount"],
                 sort_key=("denial_rate_pct", True))


@template("capstone")
def cap_category_report(rng, ctx):
    return Drill("A **root-cause report**: category (from denial_codes), **denied_claims**, **revenue_at_risk** (2 decimals), **share_of_denials_pct** (1 decimal, share of all denied claims); most denials first.",
                 "SELECT d.category,\n       COUNT(*) AS denied_claims,\n       ROUND(SUM(c.billed_amount), 2) AS revenue_at_risk,\n       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS share_of_denials_pct\nFROM claims c\nJOIN denial_codes d ON d.code = c.denial_code\nWHERE c.claim_status = 'Denied'\nGROUP BY d.category\nORDER BY denied_claims DESC;",
                 ["JOIN for the category, GROUP BY it, and a window total for the share.", "ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS share_of_denials_pct"],
                 sort_key=("denied_claims", True))


# ================================================================ generating a test
def _acceptable(df: pd.DataFrame) -> bool:
    """Reject empty, huge, or all-zero answers: they make poor questions."""
    if df is None or df.empty or df.shape[1] == 0 or len(df) > 500:
        return False
    if len(df) == 1:
        nums = df.select_dtypes("number")
        if nums.shape[1] and bool((nums.fillna(0) == 0).all(axis=None)):
            return False
    return True


def generate_set(con, lesson_ids, n: int, seed: int) -> list:
    """Draw up to `n` distinct, validated drills from the templates of `lesson_ids`. Same seed, same test."""
    rng = random.Random(seed)
    ctx = build_context(con)
    pool = [(lid, t) for lid in lesson_ids for t in TEMPLATES.get(lid, [])]
    if not pool:
        return []
    rng.shuffle(pool)
    drills, seen = [], set()
    attempts, i = 0, 0
    while len(drills) < n and attempts < n * 15:
        lid, tpl = pool[i % len(pool)]
        i += 1
        attempts += 1
        try:
            d = tpl(rng, ctx)
        except Exception:  # noqa: BLE001 - a template that cannot fill itself is simply skipped
            continue
        key = " ".join(d.solution.split()).lower()
        if key in seen:
            continue
        df, err, _ = sql_lab.run_query(con, d.solution, max_rows=100000)
        if err or not _acceptable(df):
            continue
        seen.add(key)
        d.lesson, d.template = lid, tpl.__name__
        drills.append(d.to_dict())
    return drills


def template_count(lesson_id: str) -> int:
    return len(TEMPLATES.get(lesson_id, []))


# ================================================================ extra variety: cte and window
@template("cte")
def cte_top_n(rng, ctx):
    col, word = _dim(rng)
    n = _pick(rng, [2, 3])
    metric, name, expr = _pick(rng, [("denial rate", "denial_rate_pct", RATE), ("revenue at risk", "revenue_at_risk", DENIED_DOLLARS)])
    return Drill("Using a CTE named **per_{}** with the {} of every {}, return the **top {} {}s**: {}, **{}**; highest first.".format(word, metric, word, n, word, col, name),
                 "WITH per_{} AS (\n    SELECT {},\n           {} AS {}\n    FROM claims\n    GROUP BY {}\n)\nSELECT {}, {}\nFROM per_{}\nORDER BY {} DESC\nLIMIT {};".format(word, col, expr, name, col, col, name, word, name, n),
                 ["Aggregate in the CTE, then sort and LIMIT the CTE.", "WITH per_{} AS (...) SELECT ... FROM per_{} ORDER BY {} DESC LIMIT {}".format(word, word, name, n)],
                 sort_key=(name, True))


@template("cte")
def cte_within(rng, ctx):
    col, word = _dim(rng)
    other = "account_name" if col == "payer" else "payer"
    v = _pick(rng, _values(ctx, other))
    return Drill("For **{}** only: using a CTE named **rates**, list the {}s whose denial rate is **above {}'s overall denial rate**: {}, **denial_rate_pct** (1 decimal); highest first.".format(v, word, v, col),
                 "WITH rates AS (\n    SELECT {},\n           {} AS denial_rate_pct\n    FROM claims\n    WHERE {} = '{}'\n    GROUP BY {}\n)\nSELECT {}, denial_rate_pct\nFROM rates\nWHERE denial_rate_pct > (\n    SELECT 100.0 * {} / COUNT(*) FROM claims WHERE {} = '{}'\n)\nORDER BY denial_rate_pct DESC;".format(col, RATE, other, v, col, col, DENIED_1_0, other, v),
                 ["Both the CTE and the subquery need the same WHERE {} = '{}' filter.".format(other, v),
                  "WITH rates AS (SELECT {}, <rate> FROM claims WHERE {} = '{}' GROUP BY {}) SELECT ... WHERE denial_rate_pct > (SELECT <rate> FROM claims WHERE {} = '{}')".format(col, other, v, col, other, v)],
                 sort_key=("denial_rate_pct", True))


@template("cte")
def cte_above_avg_dim(rng, ctx):
    col, word = _dim(rng)
    metric, name, expr = _pick(rng, [("revenue at risk", "revenue_at_risk", "ROUND(SUM(billed_amount), 2)"), ("denied claims", "denied_claims", "COUNT(*)")])
    return Drill("Using a CTE named **per_{}** ({} per {}, denied claims only), list the {}s whose {} is **above the average across {}s**: {}, **{}**.".format(word, metric, word, word, metric, word, col, name),
                 "WITH per_{} AS (\n    SELECT {},\n           {} AS {}\n    FROM claims\n    WHERE claim_status = 'Denied'\n    GROUP BY {}\n)\nSELECT {}, {}\nFROM per_{}\nWHERE {} > (SELECT AVG({}) FROM per_{});".format(word, col, expr, name, col, col, name, word, name, name, word),
                 ["The subquery averages the CTE's own column.", "WHERE {} > (SELECT AVG({}) FROM per_{})".format(name, name, word)])


@template("cte")
def cte_count_above(rng, ctx):
    col, word = _dim(rng)
    return Drill("Using a CTE of denial rates per {}, **how many {}s** have a rate above the overall rate? One column, **n_above**.".format(word, word),
                 "WITH rates AS (\n    SELECT {},\n           100.0 * {} / COUNT(*) AS rate\n    FROM claims\n    GROUP BY {}\n)\nSELECT COUNT(*) AS n_above\nFROM rates\nWHERE rate > (SELECT 100.0 * {} / COUNT(*) FROM claims);".format(col, DENIED_1_0, col, DENIED_1_0),
                 ["Count the rows of the CTE that pass the comparison.", "SELECT COUNT(*) AS n_above FROM rates WHERE rate > (SELECT <overall rate> FROM claims)"])


@template("cte")
def cte_month_extreme(rng, ctx):
    hi = rng.random() < 0.6
    return Drill("Using a CTE named **monthly** (denial rate per month), return the month with the **{} denial rate**: month, **denial_rate_pct** (1 decimal).".format("highest" if hi else "lowest"),
                 "WITH monthly AS (\n    SELECT strftime('%Y-%m', claim_submission_date) AS month,\n           {} AS denial_rate_pct\n    FROM claims\n    GROUP BY month\n)\nSELECT month, denial_rate_pct\nFROM monthly\nWHERE denial_rate_pct = (SELECT {}(denial_rate_pct) FROM monthly);".format(RATE, "MAX" if hi else "MIN"),
                 ["Read the CTE twice: once for the rows, once for the {} in a subquery.".format("MAX" if hi else "MIN"), "WHERE denial_rate_pct = (SELECT {}(denial_rate_pct) FROM monthly)".format("MAX" if hi else "MIN")])


@template("cte")
def cte_two_filtered(rng, ctx):
    col, word = _dim(rng)
    other = "account_name" if col == "payer" else "payer"
    v = _pick(rng, _values(ctx, other))
    return Drill("For **{}** only, with two CTEs **totals** and **denied** (per {}), join them to return {}, **total_claims**, **denied_claims**, **denial_rate_pct** (1 decimal).".format(v, word, col),
                 "WITH totals AS (\n    SELECT {}, COUNT(*) AS total_claims\n    FROM claims\n    WHERE {} = '{}'\n    GROUP BY {}\n),\ndenied AS (\n    SELECT {}, COUNT(*) AS denied_claims\n    FROM claims\n    WHERE {} = '{}' AND claim_status = 'Denied'\n    GROUP BY {}\n)\nSELECT t.{}, t.total_claims, d.denied_claims,\n       ROUND(100.0 * d.denied_claims / t.total_claims, 1) AS denial_rate_pct\nFROM totals t\nJOIN denied d ON d.{} = t.{};".format(col, other, v, col, col, other, v, col, col, col, col),
                 ["Filter both CTEs to {}; join on {}.".format(v, col), "WITH totals AS (... WHERE {} = '{}' ...), denied AS (... WHERE {} = '{}' AND claim_status = 'Denied' ...) SELECT ... JOIN ... ON d.{} = t.{}".format(other, v, other, v, col, col)])


@template("window")
def w_rank_within(rng, ctx):
    col, word = _dim(rng)
    other = "account_name" if col == "payer" else "payer"
    v = _pick(rng, _values(ctx, other))
    metric, name, expr = _pick(rng, [("denial rate", "denial_rate_pct", RATE), ("revenue at risk", "revenue_at_risk", DENIED_DOLLARS), ("denied claims", "denied_claims", DENIED_1_0)])
    return Drill("For **{}** only, **rank the {}s by {}** (1 = highest): {}, **{}**, **rank_no**; ordered by rank.".format(v, word, metric, col, name),
                 "WITH per_{} AS (\n    SELECT {},\n           {} AS {}\n    FROM claims\n    WHERE {} = '{}'\n    GROUP BY {}\n)\nSELECT {}, {},\n       RANK() OVER (ORDER BY {} DESC) AS rank_no\nFROM per_{}\nORDER BY rank_no;".format(word, col, expr, name, other, v, col, col, name, name, word),
                 ["Filter inside the CTE, rank outside it.", "RANK() OVER (ORDER BY {} DESC) AS rank_no".format(name)],
                 sort_key=("rank_no", False))


@template("window")
def w_topk_per_dim(rng, ctx):
    col, word = _dim(rng)
    k = _pick(rng, [2, 3])
    return Drill("The **{} most expensive denied claims for each {}**: {}, claim_id, billed_amount, **rn** (1 = most expensive). Use ROW_NUMBER() and keep rn <= {}.".format(k, word, col, k),
                 "WITH ranked AS (\n    SELECT {}, claim_id, billed_amount,\n           ROW_NUMBER() OVER (PARTITION BY {} ORDER BY billed_amount DESC) AS rn\n    FROM claims\n    WHERE claim_status = 'Denied'\n)\nSELECT {}, claim_id, billed_amount, rn\nFROM ranked\nWHERE rn <= {};".format(col, col, col, k),
                 ["ROW_NUMBER restarts at 1 for each partition; filter the CTE on rn.", "WHERE rn <= {}".format(k)])


@template("window")
def w_running_dim(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    return Drill("For **{}**: **running total of denied claims by month**: month, **denied_claims**, **running_total**; oldest first.".format(v),
                 "WITH monthly AS (\n    SELECT strftime('%Y-%m', claim_submission_date) AS month,\n           COUNT(*) AS denied_claims\n    FROM claims\n    WHERE claim_status = 'Denied'\n      AND {} = '{}'\n    GROUP BY month\n)\nSELECT month, denied_claims,\n       SUM(denied_claims) OVER (ORDER BY month) AS running_total\nFROM monthly\nORDER BY month;".format(col, v),
                 ["Filter to {} inside the CTE; the running SUM goes outside.".format(v), "SUM(denied_claims) OVER (ORDER BY month) AS running_total"],
                 sort_key=("month", False))


@template("window")
def w_lag_dim(rng, ctx):
    col, word = _dim(rng)
    v = _pick(rng, _values(ctx, col))
    return Drill("For **{}**: **month-over-month change in denied claims**: month, **denied_claims**, **change_vs_prev** (NULL for the first month); oldest first.".format(v),
                 "WITH monthly AS (\n    SELECT strftime('%Y-%m', claim_submission_date) AS month,\n           COUNT(*) AS denied_claims\n    FROM claims\n    WHERE claim_status = 'Denied'\n      AND {} = '{}'\n    GROUP BY month\n)\nSELECT month, denied_claims,\n       denied_claims - LAG(denied_claims) OVER (ORDER BY month) AS change_vs_prev\nFROM monthly\nORDER BY month;".format(col, v),
                 ["LAG reads the previous row in the window's order.", "denied_claims - LAG(denied_claims) OVER (ORDER BY month)"],
                 sort_key=("month", False))


@template("window")
def w_share_within(rng, ctx):
    col, word = _dim(rng)
    other = "account_name" if col == "payer" else "payer"
    v = _pick(rng, _values(ctx, other))
    return Drill("Within **{}**, each {}'s **share of its denied claims**: {}, **denied_claims**, **share_pct** (1 decimal); largest first.".format(v, word, col),
                 "SELECT {},\n       COUNT(*) AS denied_claims,\n       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS share_pct\nFROM claims\nWHERE claim_status = 'Denied'\n  AND {} = '{}'\nGROUP BY {}\nORDER BY share_pct DESC;".format(col, other, v, col),
                 ["SUM(COUNT(*)) OVER () totals the groups that survived WHERE.", "ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS share_pct"],
                 sort_key=("share_pct", True))


@template("window")
def w_dense_rank_codes(rng, ctx):
    return Drill("**Rank denial codes by how often they occur** with DENSE_RANK (1 = most common): denial_code, **denied_claims**, **rank_no**; ordered by rank.",
                 "WITH per_code AS (\n    SELECT denial_code, COUNT(*) AS denied_claims\n    FROM claims\n    WHERE claim_status = 'Denied'\n    GROUP BY denial_code\n)\nSELECT denial_code, denied_claims,\n       DENSE_RANK() OVER (ORDER BY denied_claims DESC) AS rank_no\nFROM per_code\nORDER BY rank_no, denial_code;",
                 ["DENSE_RANK leaves no gaps after ties (1, 2, 2, 3), RANK does (1, 2, 2, 4).", "DENSE_RANK() OVER (ORDER BY denied_claims DESC) AS rank_no"],
                 sort_key=("rank_no", False))
