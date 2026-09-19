"""Practice tests inside the SQL Lab: a run of 10 to 50 generated questions for one lesson.

State per lesson (in st.session_state, prefixed drill_<name>_<lesson>):
  set       the list of question dicts for the current test
  pos       index of the question being answered
  marks     {question index: "correct" | "seen" | "skipped"}
  judged    indexes already counted in the lifetime stats
  stats     {"attempted": n, "correct": n} across every test in this session
  seed      how many tests have been started (drives the random seed)
  editor, hints, solution, result, feedback   the current question's widgets
"""
from __future__ import annotations

import inspect

import streamlit as st

from . import sql_drills, sql_lab

_WIDE_BUTTON = ({"width": "stretch"} if "width" in inspect.signature(st.button).parameters
                else {"use_container_width": True})
SIZES = [10, 20, 30, 50]


def _md(text: str) -> str:
    """Streamlit markdown treats $...$ as math; questions mention dollars."""
    return text.replace("$", "\\$")


def _key(lesson_id: str, name: str) -> str:
    return "drill_{}_{}".format(name, lesson_id)


def _reset_question(lid: str) -> None:
    st.session_state[_key(lid, "editor")] = ""
    st.session_state[_key(lid, "hints")] = 0
    st.session_state[_key(lid, "solution")] = False
    st.session_state[_key(lid, "result")] = None
    st.session_state[_key(lid, "feedback")] = None


def _advance(lid: str) -> None:
    st.session_state[_key(lid, "pos")] = st.session_state.get(_key(lid, "pos"), 0) + 1
    _reset_question(lid)


def _skip(lid: str) -> None:
    pos = st.session_state.get(_key(lid, "pos"), 0)
    marks = st.session_state.setdefault(_key(lid, "marks"), {})
    marks.setdefault(pos, "skipped")
    _advance(lid)


def _start(lid: str, drills: list) -> None:
    st.session_state[_key(lid, "set")] = drills
    st.session_state[_key(lid, "pos")] = 0
    st.session_state[_key(lid, "marks")] = {}
    st.session_state[_key(lid, "judged")] = set()
    _reset_question(lid)


def _end(lid: str) -> None:
    st.session_state[_key(lid, "set")] = None


def _set(key, value) -> None:
    st.session_state[key] = value


def _render_result(result, show_table, key_suffix: str) -> None:
    if not result:
        return
    df, err, note = result
    if err:
        st.error(err)
    elif df is not None:
        st.caption("{:,} row{}{}".format(len(df), "" if len(df) == 1 else "s", (" · " + note) if note else ""))
        show_table(df, key="drill_table_" + key_suffix)


def render_practice(con, lesson, lesson_ids: list, idx: int, show_table) -> None:
    lid = lesson.id
    K = lambda name: _key(lid, name)  # noqa: E731
    stats = st.session_state.setdefault(K("stats"), {"attempted": 0, "correct": 0})
    drills = st.session_state.get(K("set"))

    st.markdown("#### Practice test: {}".format(lesson.title.split(":")[0]))

    # ------------------------------------------------------------ not started
    if not drills:
        st.caption("Questions are generated from the data, so every test is different and there are "
                   "far more than you can exhaust. Start with 10; work up to 50.")
        c1, c2, c3 = st.columns([1, 2, 2])
        n = c1.selectbox("Questions", SIZES, index=1, key=K("n"))
        mix = c2.checkbox("Mix in earlier lessons", key=K("mix"), value=False, disabled=idx == 0,
                          help="Draw questions from this lesson and every lesson before it.")
        if c3.button("Start test", type="primary", key=K("start"), **_WIDE_BUTTON):
            st.session_state[K("seed")] = st.session_state.get(K("seed"), 0) + 1
            ids = lesson_ids[:idx + 1] if mix else [lid]
            drills = sql_drills.generate_set(con, ids, int(n), seed=hash((lid, st.session_state[K("seed")])) % 100000)
            _start(lid, drills)
            st.rerun()
        if stats["attempted"]:
            st.caption("This session so far: {} correct of {} attempted in this lesson.".format(stats["correct"], stats["attempted"]))
        return

    pos = st.session_state.get(K("pos"), 0)
    marks = st.session_state.setdefault(K("marks"), {})
    judged = st.session_state.setdefault(K("judged"), set())
    n_correct = sum(1 for m in marks.values() if m == "correct")

    # ------------------------------------------------------------ finished: summary
    if pos >= len(drills):
        n = len(drills)
        st.progress(1.0, text="Finished: {} of {} correct".format(n_correct, n))
        pct = 100.0 * n_correct / n if n else 0
        if pct >= 80:
            st.success("Score {} / {} ({:.0f}%). Strong. Move to the next lesson or take a 50-question run.".format(n_correct, n, pct))
        elif pct >= 50:
            st.info("Score {} / {} ({:.0f}%). Getting there. Retry the missed questions before moving on.".format(n_correct, n, pct))
        else:
            st.warning("Score {} / {} ({:.0f}%). Reread the lesson above, then retry the missed questions.".format(n_correct, n, pct))
        rows = []
        for i, d in enumerate(drills):
            status = {"correct": "Correct", "seen": "Solved after seeing the solution", "skipped": "Skipped"}.get(marks.get(i), "Not answered")
            rows.append({"#": i + 1, "Question": d["prompt"].replace("**", ""), "Outcome": status})
        show_table(__import__("pandas").DataFrame(rows), key="drill_summary_" + lid)
        missed = [d for i, d in enumerate(drills) if marks.get(i) != "correct"]
        if missed:
            with st.expander("Solutions for the {} question{} you did not get right".format(len(missed), "" if len(missed) == 1 else "s")):
                for d in missed:
                    st.markdown(_md(d["prompt"]))
                    st.code(d["solution"], language="sql")
        b1, b2, b3 = st.columns(3)
        if missed and b1.button("Retry the missed questions", type="primary", key=K("retry"), **_WIDE_BUTTON):
            _start(lid, missed)
            st.rerun()
        if b2.button("New test", key=K("new"), **_WIDE_BUTTON):
            _end(lid)
            st.rerun()
        b3.button("Back to the lesson", key=K("back"), on_click=_end, args=(lid,), **_WIDE_BUTTON)
        return

    # ------------------------------------------------------------ a question
    d = drills[pos]
    st.progress(pos / len(drills), text="Question {} of {} · {} correct so far".format(pos + 1, len(drills), n_correct))
    if d.get("lesson") and d["lesson"] != lid:
        st.caption("From an earlier lesson: {}".format(sql_lab.LESSON_BY_ID[d["lesson"]].title.split(":")[0]))
    st.markdown(_md(d["prompt"]))
    expected, exp_err, _ = sql_lab.run_query(con, d["solution"], max_rows=100000)
    if expected is not None:
        st.caption("Target shape: {:,} row{} · columns: {}".format(len(expected), "" if len(expected) == 1 else "s", ", ".join(expected.columns)))

    st.session_state.setdefault(K("editor"), "")
    st.text_area("Practice SQL", key=K("editor"), height=170, label_visibility="collapsed",
                 placeholder="Write your query here, then Run to see the result or Check to grade it.")

    b_run, b_check, b_hint, b_sol, b_skip = st.columns(5)
    run_clicked = b_run.button("Run query", key=K("run"), type="primary", **_WIDE_BUTTON)
    check_clicked = b_check.button("Check answer", key=K("check"), **_WIDE_BUTTON)
    hint_clicked = b_hint.button("Hint", key=K("hint_btn"), **_WIDE_BUTTON)
    b_sol.button("Show solution", key=K("sol_btn"), on_click=_set, args=(K("solution"), True), **_WIDE_BUTTON)
    b_skip.button("Skip", key=K("skip"), on_click=_skip, args=(lid,), **_WIDE_BUTTON)

    if run_clicked or check_clicked:
        result = sql_lab.run_query(con, st.session_state[K("editor")], max_rows=200 if run_clicked else 100000)
        st.session_state[K("result")] = result
        st.session_state[K("feedback")] = None
        if check_clicked:
            df, err, _ = result
            if pos not in judged:
                judged.add(pos)
                stats["attempted"] += 1
            if err:
                st.session_state[K("feedback")] = ("error", "Fix the error below, then check again.")
            elif expected is not None:
                sort_key = tuple(d["sort_key"]) if d.get("sort_key") else None
                ok, msg = sql_lab.compare_results(df, expected, sort_key)
                if ok:
                    if marks.get(pos) != "correct":
                        seen = bool(st.session_state.get(K("solution")))
                        marks[pos] = "seen" if seen else "correct"
                        if not seen:
                            stats["correct"] += 1
                    st.session_state[K("feedback")] = ("ok", msg)
                    st.rerun()
                else:
                    st.session_state[K("feedback")] = ("wrong", msg)
    if hint_clicked:
        st.session_state[K("hints")] = min(st.session_state.get(K("hints"), 0) + 1, len(d["hints"]))

    feedback = st.session_state.get(K("feedback"))
    if feedback:
        status, msg = feedback
        if status == "ok":
            st.success(msg if marks.get(pos) == "correct" else msg + " (Counted as solved with help, since the solution was shown.)")
            st.button("Next question", key=K("next"), type="primary", on_click=_advance, args=(lid,))
        elif status == "wrong":
            st.warning(msg)
        else:
            st.error(msg)

    _render_result(st.session_state.get(K("result")), show_table, lid)

    for i in range(st.session_state.get(K("hints"), 0)):
        st.info("Hint {}: {}".format(i + 1, _md(d["hints"][i])))
    if st.session_state.get(K("solution")):
        st.markdown("**Solution**")
        st.code(d["solution"], language="sql")
        st.button("Load solution into the editor", key=K("load"), on_click=_set, args=(K("editor"), d["solution"]))
