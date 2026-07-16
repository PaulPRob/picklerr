"""Smoke tests for the Streamlit web port (runs headless via AppTest)."""

from streamlit.testing.v1 import AppTest

PLAYERS = [f"Player{i}" for i in range(1, 10)]  # 9 → 2 courts, 1 bye


def _app() -> AppTest:
    at = AppTest.from_file("streamlit_app.py", default_timeout=60)
    at.session_state["roster"] = {p: True for p in PLAYERS}
    return at


def test_app_runs_without_errors():
    at = _app().run()
    assert not at.exception
    assert at.session_state["schedule"] is None


def test_generate_schedule():
    at = _app().run()
    at.number_input(key="rounds").set_value(3)
    at.button(key="generate").click()
    at.run()
    assert not at.exception
    schedule = at.session_state["schedule"]
    assert len(schedule.rounds) == 3
    assert all(len(r.matches) == 2 and len(r.byes) == 1
               for r in schedule.rounds)
    labels = [t.label for t in at.tabs]
    assert "Round 1" in labels and "Summary" in labels


def test_generate_rejects_too_few_players():
    at = _app().run()
    for p in PLAYERS[3:]:
        at.checkbox(key=f"chk_{p}").uncheck()
    at.button(key="generate").click()
    at.run()
    assert not at.exception
    assert at.session_state["schedule"] is None
    assert any("Tick between" in e.value for e in at.sidebar.error)


def test_add_player_to_large_roster():
    """A roster bigger than MAX_PLAYERS (e.g. a whole club in players.txt)
    must not block adding more names — the MAX_PLAYERS cap only applies to how
    many are ticked to play."""
    at = AppTest.from_file("streamlit_app.py", default_timeout=60)
    at.session_state["roster"] = {f"Member{i}": False for i in range(1, 62)}
    at.run()
    at.text_input(key="new_player").input("Zoe")
    at.button(key="FormSubmitter:add_player-Add").click()
    at.run()
    assert not at.exception
    assert "Zoe" in at.session_state["roster"]
    assert not at.sidebar.warning  # no "maximum players" complaint


def test_add_and_remove_player():
    at = _app().run()
    at.text_input(key="new_player").input("Zoe")
    at.button(key="FormSubmitter:add_player-Add").click()
    at.run()
    assert not at.exception
    assert "Zoe" in at.session_state["roster"]
    at.button(key="rm_Zoe").click()
    at.run()
    assert not at.exception
    assert "Zoe" not in at.session_state["roster"]
