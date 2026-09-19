"""The SQL Lab tab: Streamlit rendering for the lessons in sql_lab.py.

State lives in st.session_state so progress survives reruns:
  sql_lesson            the lesson id selected in the left-hand list
  sql_done              set of lesson ids answered correctly
  sql_editor_<id>       the learner's query text for that lesson
  sql_hints_<id>        how many hints have been revealed
  sql_solution_<id>     whether the solution is shown
  sql_result_<id>       (DataFrame, error, note) from the last run
  sql_feedback_<id>     (status, message) from the last check
"""
from __future__ import annotations

import inspect

import streamlit as st

from . import sql_lab, sql_practice_ui

# Newer Streamlit takes width="stretch" on buttons; older takes use_container_width=True.
_WIDE_BUTTON = ({"width": "stretch"} if "width" in inspect.signature(st.button).parameters
                else {"use_container_width": True})


def _set_state(key, value):
    st.session_state[key] = value


def _lesson_label(lesson_id: str) -> str:
    """Static label per lesson. Completion is shown in the caption, so the option labels never change."""
    idx = [l.id for l in sql_lab.LESSONS].index(lesson_id) + 1
    return "{}. {}".format(idx, sql_lab.LESSON_BY_ID[lesson_id].title.split(":")[0])


def _render_result(result, show_table, key_suffix: str):
    df, err, note = result
    if err:
        st.error(err)
    elif df is not None:
        st.caption("{:,} row{}{}".format(len(df), "" if len(df) == 1 else "s", (" · " + note) if note else ""))
        show_table(df, key="sql_table_" + key_suffix)


def render(con, show_table) -> None:
    lessons = sql_lab.LESSONS
    ids = [l.id for l in lessons]
    done = st.session_state.setdefault("sql_done", set())

    n_claims = con.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    st.markdown("## SQL Lab")
    st.caption("Twelve short lessons that build on each other. Every query runs for real against a SQLite copy of all "
               "{:,} mock claims. The sidebar filters do not apply here, so the answers stay stable while you learn.".format(n_claims))
    st.progress(len(done) / len(lessons), text="{} of {} lessons complete".format(len(done), len(lessons)))

    with st.expander("How SQL reads a query (keep this handy)"):
        st.markdown(sql_lab.CHEATSHEET_MD)
    with st.expander("Schema reference: the two tables you can query"):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**claims** · one row per claim")
            show_table(sql_lab.schema_table("claims"), key="schema_claims")
        with c2:
            st.markdown("**denial_codes** · one row per CARC code")
            show_table(sql_lab.schema_table("denial_codes"), key="schema_codes")

    nav, main = st.columns([1, 3], gap="large")
    with nav:
        st.session_state.setdefault("sql_lesson", ids[0])
        st.markdown("**Lessons**")
        # Every parameter of this widget stays identical across reruns; if labels or captions changed with
        # progress, Streamlit would treat it as a new widget and drop the selection.
        selected = st.radio("Lessons", ids, key="sql_lesson", label_visibility="collapsed",
                            format_func=_lesson_label)
        if done:
            st.caption("Completed: " + ", ".join(str(ids.index(i) + 1) for i in ids if i in done))
        st.caption("Work top to bottom. The checker marks a lesson complete when your result matches the target.")

    lesson = sql_lab.LESSON_BY_ID[selected]
    idx = ids.index(selected)
    editor_key = "sql_editor_" + lesson.id
    hints_key = "sql_hints_" + lesson.id
    solution_key = "sql_solution_" + lesson.id
    result_key = "sql_result_" + lesson.id
    feedback_key = "sql_feedback_" + lesson.id

    with main:
        st.markdown("### Step {} of {}: {}".format(idx + 1, len(lessons), lesson.title))
        if lesson.needs_window_functions and not sql_lab.supports_window_functions():
            st.warning("This machine's SQLite is older than 3.25 and does not support window functions. "
                       "Read the lesson, then skip to the next one.")
        st.markdown(lesson.concept)

        if lesson.examples:
            st.markdown("#### Worked example{}".format("s" if len(lesson.examples) > 1 else ""))
            st.caption("Read the query, then the result underneath. Every example runs live.")
            for n, (caption, sql) in enumerate(lesson.examples):
                st.markdown("*{}*".format(caption))
                st.code(sql, language="sql")
                _render_result(sql_lab.run_query(con, sql, max_rows=10), show_table, "{}_ex{}".format(lesson.id, n))

        st.markdown("#### Your turn")
        st.markdown(lesson.challenge)
        try:
            expected = sql_lab.expected_result(con, lesson)
            st.caption("Target shape: {:,} row{} · columns: {}".format(
                len(expected), "" if len(expected) == 1 else "s", ", ".join(expected.columns)))
        except RuntimeError as exc:
            expected = None
            st.warning(str(exc))

        st.session_state.setdefault(editor_key, lesson.starter)
        st.text_area("Your SQL", key=editor_key, height=190, label_visibility="collapsed",
                     help="Replace each ____ and run. Semicolon optional.")

        b_run, b_check, b_hint, b_solution, b_reset = st.columns(5)
        run_clicked = b_run.button("Run query", key="run_" + lesson.id, type="primary", **_WIDE_BUTTON)
        check_clicked = b_check.button("Check answer", key="check_" + lesson.id, **_WIDE_BUTTON)
        hint_clicked = b_hint.button("Hint", key="hint_" + lesson.id, **_WIDE_BUTTON)
        b_solution.button("Show solution", key="solution_" + lesson.id, **_WIDE_BUTTON,
                          on_click=_set_state, args=(solution_key, True))
        b_reset.button("Reset", key="reset_" + lesson.id, **_WIDE_BUTTON,
                       on_click=_set_state, args=(editor_key, lesson.starter))

        if run_clicked or check_clicked:
            result = sql_lab.run_query(con, st.session_state[editor_key], max_rows=200 if run_clicked else 100000)
            st.session_state[result_key] = result
            st.session_state[feedback_key] = None
            if check_clicked:
                df, err, _ = result
                if err:
                    st.session_state[feedback_key] = ("error", "Fix the error below, then check again.")
                elif expected is not None:
                    ok, msg = sql_lab.compare_results(df, expected, lesson.sort_key)
                    st.session_state[feedback_key] = ("ok" if ok else "wrong", msg)
                    if ok and lesson.id not in done:
                        done.add(lesson.id)
                        st.rerun()  # so the progress bar and Completed list at the top update at once
        if hint_clicked:
            st.session_state[hints_key] = min(st.session_state.get(hints_key, 0) + 1, len(lesson.hints))

        feedback = st.session_state.get(feedback_key)
        if feedback:
            status, msg = feedback
            if status == "ok":
                st.success(msg)
                if lesson.takeaway:
                    st.markdown("**Take away:** " + lesson.takeaway)
                if idx + 1 < len(ids):
                    st.button("Next lesson: {}".format(lessons[idx + 1].title), key="next_" + lesson.id, type="primary",
                              on_click=_set_state, args=("sql_lesson", ids[idx + 1]))
                else:
                    st.markdown("That was the last lesson. Head to the sandbox below and ask the data your own question.")
            elif status == "wrong":
                st.warning(msg)
            else:
                st.error(msg)

        if result_key in st.session_state:
            _render_result(st.session_state[result_key], show_table, lesson.id + "_res")

        n_hints = st.session_state.get(hints_key, 0)
        for i in range(n_hints):
            st.info("Hint {}: {}".format(i + 1, lesson.hints[i]))
        if n_hints and n_hints >= len(lesson.hints):
            st.caption("No more hints. Show the solution if you are stuck, then rebuild it from memory.")

        if st.session_state.get(solution_key):
            st.markdown("**Solution**")
            st.code(lesson.solution, language="sql")
            st.button("Load solution into the editor", key="load_" + lesson.id,
                      on_click=_set_state, args=(editor_key, lesson.solution))
            if lesson.pandas:
                with st.expander("The same idea in pandas"):
                    st.code(lesson.pandas, language="python")

        st.markdown("---")
        sql_practice_ui.render_practice(con, lesson, ids, idx, show_table)

    st.markdown("---")
    st.markdown("### Sandbox: ask the data your own question")
    st.caption("Any SELECT against `claims` or `denial_codes`. Read-only, so nothing you type can break anything.")
    st.session_state.setdefault("sql_sandbox", "SELECT payer, COUNT(*) AS claims\nFROM claims\nGROUP BY payer\nORDER BY claims DESC;")
    st.text_area("Sandbox SQL", key="sql_sandbox", height=150, label_visibility="collapsed")
    if st.button("Run", key="sandbox_run", type="primary"):
        st.session_state["sql_sandbox_result"] = sql_lab.run_query(con, st.session_state["sql_sandbox"])
    if "sql_sandbox_result" in st.session_state:
        _render_result(st.session_state["sql_sandbox_result"], show_table, "sandbox")
