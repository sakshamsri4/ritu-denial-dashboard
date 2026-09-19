# Project 1: Denial Management Dashboard

Two deliverables on the same theme:

1. **The Design canvas.** A mock medical-billing export, deliberately messy,
   cleaned with pandas and summarized into a published dashboard design. Files
   under `data/`, `scripts/` and `design/`.
2. **The Streamlit sandbox.** An interactive app for learning the analyst's job:
   a 5,000-claim generator, the domain mapping from CARC codes to business
   buckets, executive KPIs, Plotly charts, and a training companion with live
   insights and the SQL behind the numbers. Files: `app.py` and
   `denial_dashboard/`.

## Streamlit sandbox

```bash
python3 -m pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501. The sidebar filters by account and payer; the
"Mock data controls" expander changes the random seed and claim count.

### Hosting it for free (Streamlit Community Cloud)

One-click version of the steps below, once the code is on GitHub:
https://share.streamlit.io/deploy?repository=sakshamsri4/ritu-denial-dashboard&branch=main&mainModule=app.py

1. Push this folder to a GitHub repository.
2. Sign in at https://share.streamlit.io with the same GitHub account.
3. Click **Create app**, choose the repository, branch `main`, and main file `app.py`.
   Under Advanced settings pick any Python 3.9 or newer.
4. Deploy. The app gets a public link such as `https://<name>.streamlit.app` that
   anyone can open. It sleeps after a few days without visitors and wakes on the
   next visit.

Everything the app needs is in `requirements.txt`; there are no secrets or
databases to configure because all data is generated in memory.

| File | Role |
|---|---|
| `app.py` | Page layout: sidebar filters, KPI cards, charts, tables, the training tab |
| `denial_dashboard/logic.py` | The CARC mapping table, root-cause buckets, KPI definitions, groupings, the SQL |
| `denial_dashboard/data.py` | The seeded mock-claims generator and the stories planted in it |
| `denial_dashboard/charts.py` | Plotly figures, styled once |
| `denial_dashboard/training.py` | Training companion text and the live insight generator |
| `denial_dashboard/sql_lab.py` | SQL Lab engine: in-memory SQLite practice database, twelve lessons, read-only query runner, answer checker |
| `denial_dashboard/sql_lab_ui.py` | The SQL Lab tab: lesson navigation, editor, hints, progress, sandbox |
| `.streamlit/config.toml` | Theme (blues and cool greys) and toolbar settings |

The **SQL Lab** tab teaches SQL step by step on the same claims: SELECT, WHERE,
ORDER BY, aggregates, GROUP BY, CASE WHEN, HAVING, dates, JOIN, CTEs, window
functions, and a capstone that rebuilds the top-five-payers report. Each lesson
has worked examples with live output, a fill-in-the-blanks challenge, two hints,
a solution with its pandas twin, and a checker that compares your result to the
target and says what differs. A read-only sandbox sits under the lessons.

Metric definitions used by the app:

- **Denial rate** = denied ÷ all claims in view.
- **Clean claim rate** = paid on the first submission ÷ all claims in view. A claim
  paid only after rework is not clean.
- **Revenue at risk** = billed dollars on denied claims in view.

## Design canvas pipeline

## Layout

```
data/
  raw_claims.csv        2,529 messy rows as exported (generated, do not hand-edit)
  clean_claims.csv      2,341 analysis-ready claims, one row per claim
  cleaning_log.json     what each cleaning step removed or repaired
  dashboard_data.json   aggregates the dashboard renders
scripts/
  generate_mock_claims.py   builds raw_claims.csv (seeded, reproducible)
  clean_claims.py           raw -> clean + log + dashboard_data
  build_canvas.py           injects dashboard_data.json into the artboard templates
design/
  templates/            Main.dc.html and Cleaning.dc.html with a __DATA__ token
  canvas/project/       the built artboards + canvas.json that get published
```

## Run it

```bash
python3 scripts/generate_mock_claims.py && python3 scripts/clean_claims.py && python3 scripts/build_canvas.py
```

Requires Python 3.9+ with pandas and numpy.

## Definitions

- **Denial rate** = denied / (paid + denied). Pending claims are excluded from
  both sides so open work does not distort the rate.
- **Rejected vs denied.** Clearinghouse rejections are folded into Denied for the
  dashboard. The raw spelling is kept in `raw_status`.
- **Resubmissions.** A claim resubmitted after a denial counts once, by its latest
  submission. The earlier denial is still in `raw_claims.csv`.
- **Denial categories** come from the CARC code number (so CO-27 and PR-27 both
  map to Eligibility). The mapping table is `CARC` in `scripts/clean_claims.py`.

## What the raw file gets wrong on purpose

Payer names spelled six ways each, four date formats in one column, amounts as
`$1,250.00` / `1,250.00` / `1250` / `N/A`, statuses like `PD` and `Rejected`,
denial codes as `CO16` / `co-16` / `CO 16` / `16` / `CO-016`, exact duplicate
rows, resubmitted claims sharing a claim id, test records, blank payers and
statuses, lowercase CPT codes, and ICD-10 codes missing the decimal.
