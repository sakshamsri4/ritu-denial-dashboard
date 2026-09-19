"""Healthcare Denial Management sandbox.

Four small modules, each with one job, so the code reads like the analysis does:

  data.py      builds the mock claims (the "extract from the billing system")
  logic.py     the healthcare domain rules: code -> root-cause bucket, KPIs, groupings
  charts.py    Plotly figures, styled once so every chart reads as one system
  training.py  the "Analyst Training Companion": narrative, live insights, SQL
  sql_lab.py   the SQL Lab engine: practice database, twelve lessons, query runner, checker
  sql_lab_ui.py the SQL Lab tab drawn with Streamlit
  sql_drills.py question templates that generate practice tests (dozens of questions per lesson)
  sql_practice_ui.py the practice-test panel inside each lesson

app.py at the project root wires them into the Streamlit page.
"""
