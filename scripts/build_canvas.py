#!/usr/bin/env python3
"""Inject data/dashboard_data.json into the artboard templates.

Reads  design/templates/*.dc.html   (the __DATA__ token marks where the JSON goes)
Writes design/canvas/project/*.dc.html  (what gets published to the Design canvas)

Re-run after clean_claims.py so the artboards always reflect the current data.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
DATA = os.path.join(ROOT, "data", "dashboard_data.json")
TPL = os.path.join(ROOT, "design", "templates")
OUT = os.path.join(ROOT, "design", "canvas", "project")


def render(name, payload):
    with open(os.path.join(TPL, name)) as f:
        src = f.read()
    if "__DATA__" not in src:
        raise SystemExit("%s has no __DATA__ token" % name)
    # indent=1 keeps closing braces on their own lines, so no '}}' ever appears
    # inside the script block that could be mistaken for a template hole.
    blob = json.dumps(payload, indent=1, ensure_ascii=False)
    if "</script" in blob.lower():
        raise SystemExit("data contains a script terminator")
    html = src.replace("__DATA__", blob)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path, "w") as f:
        f.write(html)
    print("wrote %s (%d KB)" % (os.path.relpath(path, ROOT), len(html) // 1024))


def main():
    with open(DATA) as f:
        data = json.load(f)
    render("Main.dc.html", {k: data[k] for k in
                            ("meta", "kpis", "by_payer", "by_category", "matrix", "trend", "top_codes", "codes_by_payer")})
    render("Cleaning.dc.html", {"meta": data["meta"], "cleaning": data["cleaning"]})


if __name__ == "__main__":
    main()
