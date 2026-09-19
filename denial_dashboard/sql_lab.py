"""SQL Lab engine: the practice database, the lessons, the query runner and the answer checker.

Nothing in here touches Streamlit, so the lessons can be tested from a plain
Python session. sql_lab_ui.py draws the tab.

The practice database is SQLite in memory, rebuilt from the mock claims:

  claims         one row per claim (the analyst's fact table)
  denial_codes   one row per CARC code (a lookup / dimension table)

Every lesson's expected answer is produced by running its solution SQL against
the same database, so the checker never depends on hard-coded numbers.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .logic import CATEGORY_OWNER, DENIAL_CODES

# ---------------------------------------------------------------- the practice database
SCHEMA = {
    "claims": [
        ("claim_id", "TEXT", "Unique claim number, e.g. CLM-1000001"),
        ("account_name", "TEXT", "The client whose claim it is: Xtend Health, Tia Health, ACMH, ICN PECL, Lecom"),
        ("payer", "TEXT", "Insurance payer: Medicare, UnitedHealthcare, Aetna, Cigna, Humana"),
        ("claim_submission_date", "TEXT", "Date sent to the payer, as 'YYYY-MM-DD' (sorts and compares correctly as text)"),
        ("billed_amount", "REAL", "Dollars billed on the claim"),
        ("claim_status", "TEXT", "'Paid' or 'Denied' (case matters in SQL text comparisons)"),
        ("denial_reason_code_raw", "TEXT", "The CARC code exactly as it arrived, messy: co-16, CO16, CO 16"),
        ("denial_code", "TEXT", "The same code normalized to GROUP-NUMBER, e.g. CO-16; empty for paid claims"),
        ("denial_reason_description", "TEXT", "The payer's wording for the code"),
        ("submission_count", "INTEGER", "1 = paid or denied on first submission, 2 = went through rework"),
    ],
    "denial_codes": [
        ("code", "TEXT", "The normalized CARC code; the key you join on"),
        ("description", "TEXT", "The payer's wording"),
        ("plain_english", "TEXT", "What it means at the front desk or in coding"),
        ("category", "TEXT", "The business bucket the dashboard uses"),
        ("owner", "TEXT", "Who fixes it"),
    ],
}


def build_database(df: pd.DataFrame) -> sqlite3.Connection:
    """Load the enriched claims into an in-memory SQLite database with two tables."""
    con = sqlite3.connect(":memory:", check_same_thread=False)
    claims = pd.DataFrame({
        "claim_id": df["Claim_ID"],
        "account_name": df["Account_Name"],
        "payer": df["Payer"],
        "claim_submission_date": pd.to_datetime(df["Claim_Submission_Date"]).dt.strftime("%Y-%m-%d"),
        "billed_amount": df["Billed_Amount"].astype(float),
        "claim_status": df["Claim_Status"],
        "denial_reason_code_raw": df["Denial_Reason_Code"],
        "denial_code": df["Denial_Code_Clean"],
        "denial_reason_description": df["Denial_Reason_Description"],
        "submission_count": df["Submission_Count"].astype(int),
    })
    claims.to_sql("claims", con, index=False)
    codes = pd.DataFrame([{
        "code": code, "description": m["description"], "plain_english": m["plain_english"],
        "category": m["category"], "owner": CATEGORY_OWNER[m["category"]],
    } for code, m in DENIAL_CODES.items()])
    codes.to_sql("denial_codes", con, index=False)
    return con


def schema_table(table: str) -> pd.DataFrame:
    return pd.DataFrame(SCHEMA[table], columns=["column", "type", "what it holds"])


def supports_window_functions() -> bool:
    return sqlite3.sqlite_version_info >= (3, 25, 0)


# ---------------------------------------------------------------- running queries safely
_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_READ_ONLY_STARTS = ("select", "with", "explain")

FRIENDLY_ERRORS = [
    (r"no such column: (\S+)",
     "SQLite cannot find a column called `{0}`. Column names are lowercase with underscores; check the schema reference. "
     "If you aliased a table (FROM claims c) use the alias: c.payer."),
    (r"no such table: (\S+)",
     "There is no table called `{0}`. The two tables are `claims` and `denial_codes`."),
    (r'near "(.+?)": syntax error',
     "Syntax error near `{0}`. The usual causes: a missing comma between columns, a comma after the last column, "
     "a misspelled keyword, or a quote that was opened and not closed."),
    (r"misuse of aggregate",
     "You mixed an aggregate (COUNT, SUM, AVG) with a plain column. Either add GROUP BY for that column, "
     "or aggregate it too."),
    (r"ambiguous column name: (\S+)",
     "Both tables have a column called `{0}`. Say which one you mean with the table alias, e.g. c.{0}."),
    (r"a GROUP BY clause is required before HAVING",
     "HAVING only works after GROUP BY. Filtering rows (not groups) belongs in WHERE."),
    (r"aggregate functions are not allowed in the WHERE clause",
     "WHERE runs before grouping, so it cannot see COUNT or SUM. Use HAVING to filter on an aggregate."),
]


def friendly_error(msg: str) -> str:
    for pattern, text in FRIENDLY_ERRORS:
        m = re.search(pattern, msg)
        if m:
            return text.format(*m.groups()) + "\n\nSQLite said: " + msg
    return "SQLite said: " + msg


def run_query(con: sqlite3.Connection, sql: str, max_rows: int = 500):
    """Run one read-only statement. Returns (DataFrame or None, error text or None, note or None)."""
    stripped = _COMMENT_RE.sub("", sql or "").strip().rstrip(";").strip()
    if not stripped:
        return None, "Write a query first.", None
    if ";" in stripped:
        return None, "One statement at a time: remove the extra semicolon.", None
    if not stripped.lower().startswith(_READ_ONLY_STARTS):
        return None, "This lab is read-only. Start the query with SELECT (or WITH for a CTE).", None
    if re.search(r"\b(insert|update|delete|drop|alter|create|replace|attach|pragma)\b", stripped, re.I):
        return None, "This lab is read-only: SELECT statements only.", None
    try:
        df = pd.read_sql_query(stripped, con)
    except Exception as exc:  # noqa: BLE001 - the whole point is to explain any SQL error
        return None, friendly_error(str(exc)), None
    note = None
    if len(df) > max_rows:
        note = "Showing the first {:,} of {:,} rows.".format(max_rows, len(df))
        df = df.head(max_rows)
    return df, None, note


# ---------------------------------------------------------------- checking answers
def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    for c in out.columns:
        col = out[c]
        try:
            num = pd.to_numeric(col)
            out[c] = num.astype(float).round(2)
        except (ValueError, TypeError):
            out[c] = col.astype(str).str.strip()
    return out.reset_index(drop=True)


def compare_results(got: pd.DataFrame, expected: pd.DataFrame, sort_key=None):
    """Return (passed, message). Order-insensitive on rows, then checks the requested sort if any."""
    g, e = _normalize(got), _normalize(expected)
    notes = []
    if g.shape[1] != e.shape[1]:
        return False, ("Your result has {} column{}; the target has {}: {}. Compare your SELECT list with the "
                       "challenge.".format(g.shape[1], "" if g.shape[1] == 1 else "s", e.shape[1], ", ".join(e.columns)))
    if list(g.columns) != list(e.columns):
        if set(g.columns) == set(e.columns):
            g = g[list(e.columns)]
        else:
            notes.append("Your column names ({}) differ from the target ({}); values were compared by position. "
                         "Use AS to name columns the way the report expects.".format(", ".join(g.columns), ", ".join(e.columns)))
            g.columns = e.columns
    if len(g) != len(e):
        hint = ("Too many rows usually means a WHERE or HAVING condition is missing or too loose; too few means one is "
                "too strict, or LIMIT is wrong.")
        return False, "Your result has {:,} rows; the target has {:,}. {}".format(len(g), len(e), hint)
    order = list(e.columns)
    gs = g.sort_values(order, kind="stable").reset_index(drop=True)
    es = e.sort_values(order, kind="stable").reset_index(drop=True)
    for c in order:
        a, b = gs[c], es[c]
        same = (a == b) | (a.isna() & b.isna())
        if not bool(same.all()):
            sample = int(np.flatnonzero(~same.to_numpy())[0])
            return False, ("Values in column `{}` differ (for example you have {} where the target has {}). "
                           "Check the rounding, the WHERE conditions, and which column you aggregated."
                           .format(c, a.iloc[sample], b.iloc[sample]))
    if sort_key:
        col, descending = sort_key
        col = col.lower()
        if col in g.columns:
            vals = g[col].to_numpy()
            ok = np.all(vals[:-1] >= vals[1:]) if descending else np.all(vals[:-1] <= vals[1:])
            if not ok:
                return False, ("The numbers are right but the rows are not in the requested order. Sort by `{}` {}."
                               .format(col, "descending (DESC)" if descending else "ascending"))
    msg = "Correct. The result matches the target exactly."
    if notes:
        msg += " " + " ".join(notes)
    return True, msg


# ---------------------------------------------------------------- lessons
@dataclass
class Lesson:
    id: str
    title: str
    concept: str
    challenge: str
    starter: str
    solution: str
    hints: list
    examples: list = field(default_factory=list)   # [(caption, sql), ...]
    sort_key: tuple = None                          # (column, descending) to verify ORDER BY
    pandas: str = ""
    takeaway: str = ""
    needs_window_functions: bool = False


CHEATSHEET_MD = """
You **write** a query in this order, and SQL **runs** it in a different one. Knowing the running
order explains most beginner errors (why WHERE cannot see a COUNT, why an alias made in SELECT
works in ORDER BY but not in WHERE).

| You write | SQL runs | What happens |
|---|---|---|
| `SELECT`   | 5th | pick and compute the output columns |
| `FROM` / `JOIN` | 1st | find the table(s) and match rows across them |
| `WHERE`    | 2nd | keep only the rows that pass the test |
| `GROUP BY` | 3rd | fold the surviving rows into one row per group |
| `HAVING`   | 4th | keep only the groups that pass the test |
| `ORDER BY` | 6th | sort the output |
| `LIMIT`    | 7th | trim the output |

Three habits: text in **single quotes** (`'Denied'`), names with **AS** (`COUNT(*) AS denied_claims`),
and **100.0** not 100 when you want a percentage with decimals.
"""

_RATE_EXPR = "ROUND(100.0 * SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) / COUNT(*), 1)"

LESSONS = [
    Lesson(
        id="select",
        title="SELECT: look at the data",
        concept="""
A database keeps data in **tables**: rows and columns, like one sheet of a workbook. Our billing
extract is a table called `claims`, one row per claim, one column per fact about it.

Every query has a shape you will type hundreds of times:

```sql
SELECT column_a, column_b    -- which columns you want
FROM   claims                -- which table they live in
LIMIT  10;                   -- how many rows to show
```

`*` means every column. `LIMIT` only trims what you see; it never changes the data.
""",
        examples=[
            ("Every column, first ten rows", "SELECT *\nFROM claims\nLIMIT 10;"),
            ("Only the columns you need", "SELECT claim_id, payer, claim_status, billed_amount\nFROM claims\nLIMIT 10;"),
        ],
        challenge="Show the **claim_id**, **account_name** and **billed_amount** of the first **5** claims in the table.",
        starter="SELECT ____\nFROM claims\nLIMIT ____;",
        solution="SELECT claim_id, account_name, billed_amount\nFROM claims\nLIMIT 5;",
        hints=["List the three column names after SELECT, separated by commas.",
               "LIMIT 5 keeps only five rows."],
        pandas="df[['Claim_ID', 'Account_Name', 'Billed_Amount']].head(5)",
        takeaway="SELECT picks columns, FROM names the table, LIMIT trims rows. Everything else in SQL slots in between.",
    ),
    Lesson(
        id="where",
        title="WHERE: keep only the rows you care about",
        concept="""
`WHERE` tests every row and keeps the ones that pass. Denial management lives on this clause:
*show me the denied ones*.

- Compare with `=`, `<>` (not equal), `>`, `<`, `>=`, `<=`.
- Combine tests with `AND` and `OR`.
- Text goes in single quotes and is case-sensitive here: `'Denied'`, not `'denied'`. Numbers have no quotes.
""",
        examples=[
            ("Denied claims only", "SELECT claim_id, payer, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\nLIMIT 10;"),
            ("Three tests at once", "SELECT claim_id, account_name, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND payer = 'Medicare'\n  AND billed_amount > 5000\nLIMIT 10;"),
        ],
        challenge="List every **denied Aetna claim billed above \\$10,000**. Show claim_id, account_name and billed_amount.",
        starter="SELECT claim_id, account_name, billed_amount\nFROM claims\nWHERE ____;",
        solution="SELECT claim_id, account_name, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND payer = 'Aetna'\n  AND billed_amount > 10000;",
        hints=["You need three tests joined with AND.",
               "Text values need single quotes: payer = 'Aetna'. Numbers do not: billed_amount > 10000."],
        pandas="mask = (df.Claim_Status == 'Denied') & (df.Payer == 'Aetna') & (df.Billed_Amount > 10000)\ndf.loc[mask, ['Claim_ID', 'Account_Name', 'Billed_Amount']]",
        takeaway="WHERE filters rows before anything is counted. If a row should not be in the answer at all, this is where it leaves.",
    ),
    Lesson(
        id="order",
        title="ORDER BY: sort the result",
        concept="""
`ORDER BY` sorts the output. `DESC` puts the largest first; `ASC` (the default) the smallest.
You can sort by more than one column: `ORDER BY payer, billed_amount DESC`.

Because sorting happens near the end, you can sort by any column in your result, including one
you named with `AS`. `ORDER BY` plus `LIMIT` is how you get a *top 10*.
""",
        examples=[
            ("Biggest denied claims first", "SELECT claim_id, payer, account_name, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\nORDER BY billed_amount DESC\nLIMIT 10;"),
        ],
        challenge="Show the **10 largest denied claims**, largest first: claim_id, payer, billed_amount.",
        starter="SELECT claim_id, payer, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\nORDER BY ____\nLIMIT 10;",
        solution="SELECT claim_id, payer, billed_amount\nFROM claims\nWHERE claim_status = 'Denied'\nORDER BY billed_amount DESC\nLIMIT 10;",
        hints=["ORDER BY takes a column name, then ASC or DESC.", "Largest first means DESC."],
        sort_key=("billed_amount", True),
        pandas="df[df.Claim_Status == 'Denied'].nlargest(10, 'Billed_Amount')[['Claim_ID', 'Payer', 'Billed_Amount']]",
        takeaway="Sorting is presentation. It never changes which rows are in the answer, only the order you read them in.",
    ),
    Lesson(
        id="aggregate",
        title="COUNT, SUM, AVG: one number from many rows",
        concept="""
An **aggregate function** folds many rows into one value. `COUNT(*)` counts rows, `SUM` adds a
column up, `AVG` averages it, `MIN` and `MAX` find the ends. `ROUND(x, 2)` tidies decimals.

Name every computed column with `AS`, otherwise the column is called `SUM(billed_amount)` and
nobody downstream can use it. This is how a KPI card is born: *Total Revenue at Risk* is one `SUM`.
""",
        examples=[
            ("The KPI cards, in SQL", "SELECT COUNT(*)                     AS denied_claims,\n       ROUND(SUM(billed_amount), 2) AS revenue_at_risk,\n       ROUND(AVG(billed_amount), 2) AS avg_denied_amount\nFROM claims\nWHERE claim_status = 'Denied';"),
        ],
        challenge=("For **denied UnitedHealthcare claims**, return the number of claims as `denied_claims`, the total billed as "
                   "`revenue_at_risk` and the average billed as `avg_denied_amount`, both rounded to 2 decimals."),
        starter="SELECT COUNT(*) AS denied_claims,\n       ____ AS revenue_at_risk,\n       ____ AS avg_denied_amount\nFROM claims\nWHERE ____;",
        solution="SELECT COUNT(*) AS denied_claims,\n       ROUND(SUM(billed_amount), 2) AS revenue_at_risk,\n       ROUND(AVG(billed_amount), 2) AS avg_denied_amount\nFROM claims\nWHERE claim_status = 'Denied'\n  AND payer = 'UnitedHealthcare';",
        hints=["SUM(billed_amount) and AVG(billed_amount), each wrapped in ROUND(..., 2).",
               "The WHERE needs both claim_status = 'Denied' and payer = 'UnitedHealthcare'."],
        pandas="d = df[(df.Claim_Status == 'Denied') & (df.Payer == 'UnitedHealthcare')]\nlen(d), d.Billed_Amount.sum().round(2), d.Billed_Amount.mean().round(2)",
        takeaway="Aggregates answer 'how many' and 'how much'. Without GROUP BY they answer it once, for the whole filtered table.",
    ),
    Lesson(
        id="groupby",
        title="GROUP BY: one row per payer",
        concept="""
`GROUP BY` runs the aggregates once **per group** instead of once overall. `GROUP BY payer` gives
one row per payer; `GROUP BY account_name, payer` one row per combination.

The one rule beginners trip on: **every column in SELECT is either in the GROUP BY or inside an
aggregate.** A plain column that is neither has no single value for the group, so the database refuses.

This clause is the engine behind the Payer Wall of Shame.
""",
        examples=[
            ("Denials by payer", "SELECT payer,\n       COUNT(*)                     AS denied_claims,\n       ROUND(SUM(billed_amount), 2) AS revenue_at_risk\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY payer\nORDER BY denied_claims DESC;"),
        ],
        challenge=("Denied claims and revenue at risk **by account_name**, biggest revenue at risk first. "
                   "Columns: account_name, denied_claims, revenue_at_risk (2 decimals)."),
        starter="SELECT ____,\n       COUNT(*) AS denied_claims,\n       ROUND(SUM(billed_amount), 2) AS revenue_at_risk\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY ____\nORDER BY ____;",
        solution="SELECT account_name,\n       COUNT(*) AS denied_claims,\n       ROUND(SUM(billed_amount), 2) AS revenue_at_risk\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY account_name\nORDER BY revenue_at_risk DESC;",
        hints=["The grouping column appears twice: in SELECT and in GROUP BY.",
               "ORDER BY revenue_at_risk DESC sorts by the alias you just created."],
        sort_key=("revenue_at_risk", True),
        pandas="(df[df.Claim_Status == 'Denied']\n   .groupby('Account_Name')\n   .agg(denied_claims=('Claim_ID', 'count'), revenue_at_risk=('Billed_Amount', 'sum'))\n   .sort_values('revenue_at_risk', ascending=False))",
        takeaway="GROUP BY turns a list of claims into a report: one line per thing you want to compare.",
    ),
    Lesson(
        id="casewhen",
        title="CASE WHEN: count a subset inside a group (the denial rate)",
        concept="""
A denial rate needs two counts from the **same** rows: all claims, and the denied ones. `WHERE`
cannot help, because filtering to denied claims would throw away the paid rows you need in the
denominator.

`CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END` turns each row into a 1 or a 0; `SUM` of that
is the denied count. Divide by `COUNT(*)`, multiply by `100.0` (the decimal point matters: `100`
would give whole-number division in many databases), round to one decimal.
""",
        examples=[
            ("Denial rate by payer", "SELECT payer,\n       COUNT(*) AS total_claims,\n       SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) AS denied_claims,\n       " + _RATE_EXPR + " AS denial_rate_pct\nFROM claims\nGROUP BY payer\nORDER BY denial_rate_pct DESC;"),
        ],
        challenge="The same report **by account_name**: total_claims, denied_claims, denial_rate_pct (1 decimal), highest rate first.",
        starter="SELECT account_name,\n       COUNT(*) AS total_claims,\n       SUM(CASE WHEN ____ THEN 1 ELSE 0 END) AS denied_claims,\n       ROUND(100.0 * ____ / COUNT(*), 1) AS denial_rate_pct\nFROM claims\nGROUP BY account_name\nORDER BY denial_rate_pct DESC;",
        solution="SELECT account_name,\n       COUNT(*) AS total_claims,\n       SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) AS denied_claims,\n       " + _RATE_EXPR + " AS denial_rate_pct\nFROM claims\nGROUP BY account_name\nORDER BY denial_rate_pct DESC;",
        hints=["The CASE tests claim_status = 'Denied'.",
               "The rate divides the same SUM(CASE ...) expression by COUNT(*). You must repeat the whole expression; SQL has no shortcut for reusing an alias in the same SELECT."],
        sort_key=("denial_rate_pct", True),
        pandas="(df.assign(is_denied=df.Claim_Status.eq('Denied'))\n   .groupby('Account_Name')\n   .agg(total_claims=('Claim_ID', 'count'), denied_claims=('is_denied', 'sum'))\n   .assign(denial_rate_pct=lambda g: (100 * g.denied_claims / g.total_claims).round(1)))",
        takeaway="CASE WHEN inside SUM is conditional counting. Every rate, share and percentage on the dashboard is built this way.",
    ),
    Lesson(
        id="having",
        title="HAVING: filter the groups, not the rows",
        concept="""
`WHERE` filters **rows** before grouping. `HAVING` filters **groups** after grouping, so it is the
only place you can test a `COUNT` or `SUM`.

*Denied claims* is a WHERE. *Payers with at least 800 claims* is a HAVING. Small groups make noisy
percentages (3 denials out of 12 claims is a 25% rate that means nothing); HAVING is how you keep
them off an executive's screen.
""",
        examples=[
            ("Only payers with real volume", "SELECT payer, COUNT(*) AS total_claims\nFROM claims\nGROUP BY payer\nHAVING COUNT(*) >= 800\nORDER BY total_claims DESC;"),
        ],
        challenge=("Which **account and payer combinations** have **20 or more denied claims**? "
                   "Columns: account_name, payer, denied_claims; most denials first."),
        starter="SELECT account_name, payer, COUNT(*) AS denied_claims\nFROM claims\nWHERE ____\nGROUP BY ____\nHAVING ____\nORDER BY denied_claims DESC;",
        solution="SELECT account_name, payer, COUNT(*) AS denied_claims\nFROM claims\nWHERE claim_status = 'Denied'\nGROUP BY account_name, payer\nHAVING COUNT(*) >= 20\nORDER BY denied_claims DESC;",
        hints=["WHERE keeps denied rows; GROUP BY lists both columns, separated by a comma.",
               "HAVING COUNT(*) >= 20 keeps only the big groups."],
        pandas="(df[df.Claim_Status == 'Denied']\n   .groupby(['Account_Name', 'Payer']).size().rename('denied_claims')\n   .loc[lambda s: s >= 20]\n   .sort_values(ascending=False))",
        takeaway="Row filter, then group, then group filter. If your condition mentions COUNT or SUM, it belongs in HAVING.",
    ),
    Lesson(
        id="dates",
        title="Dates: the monthly trend",
        concept="""
`claim_submission_date` is stored as text in `YYYY-MM-DD` form, which is why it sorts and compares
correctly with plain `<` and `>`. To roll days up to months, SQLite uses
`strftime('%Y-%m', claim_submission_date)`, which returns `'2026-07'`. (Other databases spell this
`DATE_TRUNC('month', ...)` or `FORMAT(...)`; the idea is identical.)

Group by that expression and you have the trend chart.
""",
        examples=[
            ("Claims per month", "SELECT strftime('%Y-%m', claim_submission_date) AS month,\n       COUNT(*) AS total_claims\nFROM claims\nGROUP BY month\nORDER BY month;"),
            ("A date window", "SELECT COUNT(*) AS claims_in_window\nFROM claims\nWHERE claim_submission_date >= '2026-06-01'\n  AND claim_submission_date <  '2026-08-01';"),
        ],
        challenge="Monthly denial rate: month, total_claims, denied_claims, denial_rate_pct (1 decimal), oldest month first.",
        starter="SELECT strftime('%Y-%m', claim_submission_date) AS month,\n       COUNT(*) AS total_claims,\n       ____ AS denied_claims,\n       ____ AS denial_rate_pct\nFROM claims\nGROUP BY month\nORDER BY month;",
        solution="SELECT strftime('%Y-%m', claim_submission_date) AS month,\n       COUNT(*) AS total_claims,\n       SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) AS denied_claims,\n       " + _RATE_EXPR + " AS denial_rate_pct\nFROM claims\nGROUP BY month\nORDER BY month;",
        hints=["The two blanks are the same CASE WHEN pattern as the last lesson.",
               "ORDER BY month sorts the text '2026-04' before '2026-05', which is exactly what you want."],
        sort_key=("month", False),
        pandas="(df.assign(month=df.Claim_Submission_Date.dt.strftime('%Y-%m'), is_denied=df.Claim_Status.eq('Denied'))\n   .groupby('month')\n   .agg(total_claims=('Claim_ID', 'count'), denied_claims=('is_denied', 'sum'))\n   .assign(denial_rate_pct=lambda g: (100 * g.denied_claims / g.total_claims).round(1)))",
        takeaway="A trend is just GROUP BY on a date truncated to the grain you want: month, week, quarter.",
    ),
    Lesson(
        id="join",
        title="JOIN: bring in the lookup table",
        concept="""
The claims table knows the **code** (CO-197) but not what it **means**. Meanings live in a second
table, `denial_codes`, one row per code. `JOIN ... ON` matches rows across the two tables on a
shared key, so every claim picks up its category and owner.

Give each table a short alias (`claims c`, `denial_codes d`) and prefix columns with it.
`JOIN` keeps only matched rows; `LEFT JOIN` keeps every claim and shows `NULL` where nothing matched.

Why the analyst normalizes before joining: the raw codes arrived as `co-16`, `CO16`, `CO 16`.
None of those equal `'CO-16'`, so a join on the raw column silently loses rows. Watch the first example.
""",
        examples=[
            ("Joining on the raw code loses matches", "SELECT COUNT(*) AS denied_claims,\n       SUM(CASE WHEN d.code IS NULL THEN 1 ELSE 0 END) AS unmatched_on_raw_code\nFROM claims c\nLEFT JOIN denial_codes d ON d.code = c.denial_reason_code_raw\nWHERE c.claim_status = 'Denied';"),
            ("Joining on the cleaned code", "SELECT c.claim_id, c.denial_code, d.category, d.plain_english\nFROM claims c\nJOIN denial_codes d ON d.code = c.denial_code\nWHERE c.claim_status = 'Denied'\nLIMIT 10;"),
        ],
        challenge=("Rebuild the root-cause ring chart: denied claims and revenue at risk **by category** (from denial_codes). "
                   "Columns: category, denied_claims, revenue_at_risk (2 decimals); most denials first."),
        starter="SELECT d.category,\n       COUNT(*) AS denied_claims,\n       ROUND(SUM(c.billed_amount), 2) AS revenue_at_risk\nFROM claims c\nJOIN denial_codes d ON ____\nWHERE c.claim_status = 'Denied'\nGROUP BY ____\nORDER BY denied_claims DESC;",
        solution="SELECT d.category,\n       COUNT(*) AS denied_claims,\n       ROUND(SUM(c.billed_amount), 2) AS revenue_at_risk\nFROM claims c\nJOIN denial_codes d ON d.code = c.denial_code\nWHERE c.claim_status = 'Denied'\nGROUP BY d.category\nORDER BY denied_claims DESC;",
        hints=["The ON clause matches d.code to the cleaned column c.denial_code.",
               "GROUP BY d.category, the column you are reporting."],
        sort_key=("denied_claims", True),
        pandas="(df[df.Is_Denied]\n   .groupby('Root_Cause_Category')\n   .agg(denied_claims=('Claim_ID', 'count'), revenue_at_risk=('Billed_Amount', 'sum')))",
        takeaway="A JOIN turns a code into a meaning. Always join on a cleaned key; a join on messy text fails quietly.",
    ),
    Lesson(
        id="cte",
        title="WITH (CTEs): build the answer in steps",
        concept="""
Real questions need two steps: *work out each payer's rate*, then *compare it to the overall rate*.
A **CTE** (`WITH name AS (...)`) gives the first step a name so the second can read it like a table.
You read it top to bottom, the way you would explain it to a colleague.

A query in parentheses inside `WHERE` is a **subquery**; here one computes the overall rate.
""",
        examples=[
            ("Payers denying above the overall rate", "WITH payer_rates AS (\n    SELECT payer,\n           " + _RATE_EXPR + " AS denial_rate_pct\n    FROM claims\n    GROUP BY payer\n)\nSELECT payer, denial_rate_pct\nFROM payer_rates\nWHERE denial_rate_pct > (\n    SELECT 100.0 * SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) / COUNT(*)\n    FROM claims\n)\nORDER BY denial_rate_pct DESC;"),
        ],
        challenge=("Do the same for **accounts**: with a CTE called account_rates, list the accounts whose denial rate is above "
                   "the overall rate. Columns: account_name, denial_rate_pct (1 decimal); highest first."),
        starter="WITH account_rates AS (\n    SELECT ____,\n           " + _RATE_EXPR + " AS denial_rate_pct\n    FROM claims\n    GROUP BY ____\n)\nSELECT account_name, denial_rate_pct\nFROM account_rates\nWHERE denial_rate_pct > (\n    SELECT ____\n    FROM claims\n)\nORDER BY denial_rate_pct DESC;",
        solution="WITH account_rates AS (\n    SELECT account_name,\n           " + _RATE_EXPR + " AS denial_rate_pct\n    FROM claims\n    GROUP BY account_name\n)\nSELECT account_name, denial_rate_pct\nFROM account_rates\nWHERE denial_rate_pct > (\n    SELECT 100.0 * SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) / COUNT(*)\n    FROM claims\n)\nORDER BY denial_rate_pct DESC;",
        hints=["Inside the CTE, select and group by account_name.",
               "The subquery is the overall rate: the same 100.0 * SUM(CASE ...) / COUNT(*) with no GROUP BY."],
        sort_key=("denial_rate_pct", True),
        pandas="rates = df.groupby('Account_Name').Is_Denied.mean() * 100\nrates[rates > df.Is_Denied.mean() * 100].sort_values(ascending=False).round(1)",
        takeaway="When a question has two steps, write two steps. A CTE per step keeps the logic readable and testable.",
    ),
    Lesson(
        id="window",
        title="Window functions: rank without collapsing",
        concept="""
`GROUP BY` collapses rows. A **window function** looks across rows but keeps every one of them.
`RANK() OVER (ORDER BY denial_rate_pct DESC)` adds a rank column; `PARTITION BY account_name`
restarts the ranking inside each account, so you can ask *which payer hurts each account most?*

The `OVER (...)` part is the window: which rows to look at and in what order.
""",
        examples=[
            ("Rank payers by denial rate", "WITH payer_rates AS (\n    SELECT payer,\n           COUNT(*) AS total_claims,\n           " + _RATE_EXPR + " AS denial_rate_pct\n    FROM claims\n    GROUP BY payer\n)\nSELECT payer, total_claims, denial_rate_pct,\n       RANK() OVER (ORDER BY denial_rate_pct DESC) AS rank_overall\nFROM payer_rates\nORDER BY rank_overall;"),
        ],
        challenge=("For **each account**, rank its payers by revenue at risk (denied dollars), 1 = most. "
                   "Columns: account_name, payer, revenue_at_risk (2 decimals), rank_in_account. Order by account_name, then rank_in_account."),
        starter="WITH at_risk AS (\n    SELECT account_name, payer,\n           ROUND(SUM(billed_amount), 2) AS revenue_at_risk\n    FROM claims\n    WHERE claim_status = 'Denied'\n    GROUP BY account_name, payer\n)\nSELECT account_name, payer, revenue_at_risk,\n       RANK() OVER (PARTITION BY ____ ORDER BY ____) AS rank_in_account\nFROM at_risk\nORDER BY account_name, rank_in_account;",
        solution="WITH at_risk AS (\n    SELECT account_name, payer,\n           ROUND(SUM(billed_amount), 2) AS revenue_at_risk\n    FROM claims\n    WHERE claim_status = 'Denied'\n    GROUP BY account_name, payer\n)\nSELECT account_name, payer, revenue_at_risk,\n       RANK() OVER (PARTITION BY account_name ORDER BY revenue_at_risk DESC) AS rank_in_account\nFROM at_risk\nORDER BY account_name, rank_in_account;",
        hints=["PARTITION BY account_name restarts the count for each account.",
               "ORDER BY revenue_at_risk DESC inside OVER gives rank 1 to the biggest."],
        pandas="g = df[df.Is_Denied].groupby(['Account_Name', 'Payer']).Billed_Amount.sum().reset_index()\ng['rank_in_account'] = g.groupby('Account_Name').Billed_Amount.rank(ascending=False, method='min')",
        takeaway="Ranking, running totals and 'compared to the group' columns are window functions. They are the step from reports to analysis.",
        needs_window_functions=True,
    ),
    Lesson(
        id="capstone",
        title="Capstone: the Top 5 payers report",
        concept="""
This is the query from the Training Companion, and you now know every part of it. Build it clause by
clause, in the order SQL runs:

1. `FROM claims`
2. `GROUP BY payer`
3. `HAVING COUNT(*) >= 50` (drop payers too small to rank fairly)
4. `SELECT` five columns: payer, total_claims, denied_claims, denial_rate_pct, revenue_at_risk
5. `ORDER BY denial_rate_pct DESC, revenue_at_risk DESC`
6. `LIMIT 5`

Revenue at risk counts only **denied** dollars, so it needs its own CASE: `SUM(CASE WHEN claim_status
= 'Denied' THEN billed_amount ELSE 0 END)`.
""",
        challenge=("Write the report: payer, total_claims, denied_claims, denial_rate_pct (1 decimal), revenue_at_risk "
                   "(2 decimals, denied dollars only). Keep payers with at least 50 claims, highest rate first (ties by "
                   "revenue at risk), top 5."),
        starter="SELECT payer,\n       ____\nFROM claims\nGROUP BY payer\nHAVING ____\nORDER BY ____\nLIMIT 5;",
        solution=("SELECT payer,\n       COUNT(*) AS total_claims,\n       SUM(CASE WHEN claim_status = 'Denied' THEN 1 ELSE 0 END) AS denied_claims,\n       "
                  + _RATE_EXPR + " AS denial_rate_pct,\n       ROUND(SUM(CASE WHEN claim_status = 'Denied' THEN billed_amount ELSE 0 END), 2) AS revenue_at_risk\n"
                  "FROM claims\nGROUP BY payer\nHAVING COUNT(*) >= 50\nORDER BY denial_rate_pct DESC, revenue_at_risk DESC\nLIMIT 5;"),
        hints=["Four aggregates: COUNT(*); SUM(CASE ... THEN 1 ELSE 0 END) for denied; the rate as 100.0 * that / COUNT(*); and SUM(CASE ... THEN billed_amount ELSE 0 END) for dollars.",
               "HAVING COUNT(*) >= 50, then ORDER BY denial_rate_pct DESC, revenue_at_risk DESC."],
        sort_key=("denial_rate_pct", True),
        pandas="See logic.top_denying_payers() in the Training Companion: the same report in pandas.",
        takeaway="You just wrote the query the dashboard runs. Every chart on the Dashboard tab is one of these, with a different GROUP BY.",
    ),
]

LESSON_BY_ID = {lesson.id: lesson for lesson in LESSONS}


def expected_result(con: sqlite3.Connection, lesson: Lesson) -> pd.DataFrame:
    df, err, _ = run_query(con, lesson.solution, max_rows=100000)
    if err:
        raise RuntimeError("Lesson %s solution failed: %s" % (lesson.id, err))
    return df
