#!/usr/bin/env python3
"""Streamlit web port of RR_pickle_picker.

Run locally with:   .venv/bin/streamlit run streamlit_app.py
Deploy by pointing Streamlit Community Cloud at this file.

The scheduling engine (scheduler.py) and the export helpers (export.py)
are reused unchanged; the PyQt6 desktop app (RR_pickle_picker.py) is not
touched and keeps working as before.

export.py imports PyQt6 at module level for its print/PDF helpers, but
the HTML and Excel exports used here are pure Python.  When PyQt6 is not
installed (as on Streamlit Cloud) a minimal stub is injected before the
import so those exports stay available.  The web app therefore offers
Phone (HTML), Excel and printable-HTML downloads; native print/PDF stays
a desktop-only feature (use the browser's print-to-PDF on the printable
HTML instead).

The roster is per-browser-session.  If a players.txt sits next to this
script (as the desktop app maintains) it seeds the roster on first load,
but the web app never writes to it - on a shared deployment every
visitor gets their own roster.
"""

from __future__ import annotations

import io
import re
import sys
import tempfile
import types
from pathlib import Path

import streamlit as st

# Make scheduler.py / export.py importable regardless of the working
# directory the app is launched from.
_APP_DIR = str(Path(__file__).parent)
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)


def _ensure_pyqt6_importable() -> None:
    """Inject a dummy PyQt6 so `import export` works without Qt installed."""
    try:
        import PyQt6  # noqa: F401
        return
    except ImportError:
        pass
    qtgui = types.ModuleType("PyQt6.QtGui")
    qtgui.QPageLayout = type("QPageLayout", (), {})
    qtgui.QTextDocument = type("QTextDocument", (), {})
    qtprint = types.ModuleType("PyQt6.QtPrintSupport")
    qtprint.QPrinter = type("QPrinter", (), {})
    pkg = types.ModuleType("PyQt6")
    pkg.QtGui = qtgui
    pkg.QtPrintSupport = qtprint
    sys.modules["PyQt6"] = pkg
    sys.modules["PyQt6.QtGui"] = qtgui
    sys.modules["PyQt6.QtPrintSupport"] = qtprint


_ensure_pyqt6_importable()

import export  # noqa: E402
import scheduler  # noqa: E402
from scheduler import (  # noqa: E402
    compute_stats,
    generate_schedule,
    num_byes,
    num_courts,
)

PLAYERS_FILE = Path(__file__).with_name("players.txt")


def _md(text: str) -> str:
    """Escape Markdown control characters in a player name."""
    return re.sub(r"([\\`*_~\[\]])", r"\\\1", text)


def _init_state() -> None:
    if "roster" not in st.session_state:
        names: list[str] = []
        if PLAYERS_FILE.exists():
            names = [n.strip() for n in PLAYERS_FILE.read_text().splitlines()
                     if n.strip()]
        st.session_state.roster = {name: True for name in names}
    st.session_state.setdefault("schedule", None)


# ----------------------------------------------------------------------
# Sidebar: roster, attendance checkboxes, rounds, generate
# ----------------------------------------------------------------------
def _sidebar() -> None:
    roster: dict[str, bool] = st.session_state.roster
    st.sidebar.header("Players")

    with st.sidebar.form("add_player", clear_on_submit=True):
        col_name, col_btn = st.columns([3, 1])
        new_name = col_name.text_input(
            "Add player", placeholder="Enter player name…",
            label_visibility="collapsed", key="new_player")
        submitted = col_btn.form_submit_button("Add")
    if submitted:
        name = new_name.strip()
        if name:
            if name.lower() in {n.lower() for n in roster}:
                st.sidebar.warning(f"“{name}” is already in the list.")
            else:
                # The roster itself has no size cap (players.txt can hold
                # the whole club); MAX_PLAYERS only limits how many can be
                # ticked to play, enforced at Generate time.
                roster[name] = True
                st.session_state[f"chk_{name}"] = True

    col_all, col_none = st.sidebar.columns(2)
    if col_all.button("All", use_container_width=True):
        for name in roster:
            st.session_state[f"chk_{name}"] = True
    if col_none.button("None", use_container_width=True):
        for name in roster:
            st.session_state[f"chk_{name}"] = False

    to_remove = None
    for name in list(roster):
        col_chk, col_rm = st.sidebar.columns([5, 1])
        key = f"chk_{name}"
        if key not in st.session_state:
            st.session_state[key] = roster[name]
        roster[name] = col_chk.checkbox(name, key=key)
        if col_rm.button("✕", key=f"rm_{name}", help=f"Remove {name}"):
            to_remove = name
    if to_remove is not None:
        del roster[to_remove]
        st.session_state.pop(f"chk_{to_remove}", None)
        st.rerun()

    playing = [n for n, ticked in roster.items() if ticked]
    n = len(playing)
    if n == 0:
        st.sidebar.caption("No players ticked.")
    elif n > scheduler.MAX_PLAYERS:
        st.sidebar.warning(
            f"{n} ticked — at most {scheduler.MAX_PLAYERS} can play. "
            f"Untick {n - scheduler.MAX_PLAYERS} before generating.")
    else:
        courts, byes = num_courts(n), num_byes(n)
        st.sidebar.markdown(
            f"**{n} playing** → {courts} court{'s' if courts != 1 else ''}, "
            f"{byes} bye{'s' if byes != 1 else ''} per round")

    st.sidebar.divider()
    rounds = st.sidebar.number_input(
        "Rounds", min_value=1, max_value=40,
        value=scheduler.DEFAULT_ROUNDS, key="rounds")

    if st.sidebar.button("Generate Schedule", type="primary",
                         use_container_width=True, key="generate"):
        if not scheduler.MIN_PLAYERS <= n <= scheduler.MAX_PLAYERS:
            st.sidebar.error(
                f"Tick between {scheduler.MIN_PLAYERS} and "
                f"{scheduler.MAX_PLAYERS} players (currently {n}).")
        else:
            with st.spinner("Optimising…"):
                st.session_state.schedule = generate_schedule(
                    playing, int(rounds))


# ----------------------------------------------------------------------
# Main area: round tabs, summary, downloads
# ----------------------------------------------------------------------
def _round_tab(rnd) -> None:
    col_courts, col_byes = st.columns([3, 1])
    with col_courts:
        for i, match in enumerate(rnd.matches, start=1):
            with st.container(border=True):
                st.caption(f"Court {i}")
                st.markdown(
                    f"**{_md(match.team1[0])} & {_md(match.team1[1])}**"
                    f" &nbsp;vs&nbsp; "
                    f"**{_md(match.team2[0])} & {_md(match.team2[1])}**")
    with col_byes:
        st.markdown("**Byes**")
        if rnd.byes:
            for name in rnd.byes:
                st.markdown(f"⏸ {_md(name)}")
        else:
            st.markdown("None")


def _summary_tab(schedule) -> None:
    stats = compute_stats(schedule)
    lines = [
        f"Players: {len(schedule.players)}    "
        f"Rounds: {len(schedule.rounds)}    "
        f"Courts per round: {num_courts(len(schedule.players))}",
        "",
        f"Pairs who partnered more than once: "
        f"{stats.repeat_partnerships}",
        f"Most times any pair partnered: {stats.max_partner_repeats}",
        f"Most times any pair faced each other: "
        f"{stats.max_opponent_repeats}",
        f"Same-partner in consecutive rounds: "
        f"{stats.consecutive_partner_repeats}",
        f"Same-opponent in consecutive rounds: "
        f"{stats.consecutive_opponent_repeats}",
        "",
        "Byes per player:",
    ]
    for name in schedule.players:
        lines.append(f"  {name}: {stats.bye_counts[name]}")
    repeats = [(sorted(pair), count)
               for pair, count in stats.partner_counts.items() if count > 1]
    if repeats:
        lines.append("")
        lines.append("Repeated partnerships:")
        for (a, b), count in sorted(repeats):
            lines.append(f"  {a} & {b}: {count} times")
    lines.append("")
    lines.append("RR Pickle Picker V1.0 Paul Roberts 2026")
    st.text("\n".join(lines))


def _downloads(schedule) -> None:
    st.divider()
    col_phone, col_excel, col_print = st.columns(3)

    with tempfile.TemporaryDirectory() as tmpdir:
        phone_path = Path(tmpdir) / "pickleball_draw.html"
        export.export_html(schedule, str(phone_path))
        phone_html = phone_path.read_bytes()
    col_phone.download_button(
        "📱 Phone (HTML)", phone_html, "pickleball_draw.html",
        mime="text/html", use_container_width=True,
        help="Self-contained page for phones — send it via WhatsApp, "
             "email or a cloud drive.")

    excel_buf = io.BytesIO()
    export.export_excel(schedule, excel_buf)
    col_excel.download_button(
        "📊 Excel (.xlsx)", excel_buf.getvalue(), "pickleball_schedule.xlsx",
        mime="application/vnd.openxmlformats-officedocument"
             ".spreadsheetml.sheet",
        use_container_width=True)

    printable = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Pickleball schedule</title></head><body>"
        + export.schedule_html(schedule) + "</body></html>")
    col_print.download_button(
        "🖨️ Printable (HTML)", printable, "pickleball_schedule.html",
        mime="text/html", use_container_width=True,
        help="Open in your browser and print — or save as PDF from the "
             "print dialog.")


def _main_area() -> None:
    st.title("🏓 RR Pickle Picker")
    schedule = st.session_state.schedule
    if schedule is None:
        st.info("Tick today's players in the sidebar, set the number of "
                "rounds, then press **Generate Schedule**.")
        return
    st.caption(
        f"{len(schedule.players)} players · {len(schedule.rounds)} rounds · "
        f"{num_courts(len(schedule.players))} courts per round")
    tabs = st.tabs([f"Round {rnd.number}" for rnd in schedule.rounds]
                   + ["Summary"])
    for tab, rnd in zip(tabs, schedule.rounds):
        with tab:
            _round_tab(rnd)
    with tabs[-1]:
        _summary_tab(schedule)
    _downloads(schedule)


def main() -> None:
    st.set_page_config(page_title="RR_pickle_picker", page_icon="🏓",
                       layout="wide")
    _init_state()
    _sidebar()
    _main_area()


main()
