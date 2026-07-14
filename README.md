# RR_pickle_picker

Pickleball round-robin doubles scheduler for 4–32 players, available as
a PyQt6 desktop GUI and as a Streamlit web app. Both front ends share
the same scheduling engine and export helpers.

## Run the desktop app

```bash
.venv/bin/python RR_pickle_picker.py
```

## Run the web app locally

```bash
.venv/bin/streamlit run streamlit_app.py
```

## Deploy the web app on Streamlit Community Cloud

1. Push this repository to GitHub.
2. Go to <https://share.streamlit.io>, sign in with GitHub, and click
   **Create app**.
3. Pick this repository and branch, set **Main file path** to
   `streamlit_app.py`, and deploy. Dependencies come from
   `requirements.txt` (Streamlit + openpyxl only — PyQt6 is not needed
   on the server; the web app stubs it out for the shared export code).

Notes on the web version: the roster lives in the browser session (it
is seeded from `players.txt` if one exists next to the script, but the
web app never writes to it, so visitors don't see each other's rosters).
Native Print/PDF is desktop-only; the web app instead offers the
**Phone (HTML)** and **Excel** downloads plus a **Printable (HTML)**
download you can print (or save as PDF) from the browser.

## Run the tests

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```

## How to use

1. Type player names into the field on the left and press Enter (or Add).
   The roster is saved to `players.txt` next to the program and reloads
   automatically next time.
2. Tick the checkboxes for the players who are actually there today
   (All / None buttons for convenience; Remove deletes a highlighted name
   from the roster).
3. Set the number of rounds (default 10) and press **Generate Schedule**.
4. Each round appears as a tab showing the courts
   (`courts = players ÷ 4`, e.g. 20 players → 5 courts) with the byes
   listed on the right. A final **Summary** tab reports fairness stats:
   repeated partnerships, opponent repeats, and byes per player.
5. Once a schedule exists, the **Print…**, **PDF…**, **Excel…** and
   **Phone (HTML)…** buttons become active. Print sends the whole
   schedule to a printer; PDF saves the same printable layout; Excel
   saves an .xlsx workbook with a "Schedule" sheet (one block per round
   plus byes) and a "Summary" sheet with the fairness stats.
6. **Phone (HTML)…** saves a single self-contained web page designed
   for phone screens. Send it to the group (WhatsApp, email, cloud
   drive) and it opens in any phone browser — no app or internet
   needed. It shows the full draw round by round, and tapping a
   player's name chip switches to a "my games" view: their court,
   partner and opponents for every round, with byes called out.
   Supports dark mode automatically. The page contains **no
   JavaScript** — the name filter is pure HTML/CSS — so it also works
   inside attachment previews that block scripts, such as WhatsApp's
   and Mail's built-in viewers on iPhone (iOS QuickLook).

## What the optimiser does

For each round it first assigns byes (leftover players when the count
isn't divisible by 4) to whoever has had the fewest byes, tie-broken by
who sat out longest ago — nobody gets a second bye until everyone has had
one. It then searches court assignments with random-restart hill-climbing,
minimising a weighted cost that penalises (heaviest first): repeating a
partner, repeating a partner/opponent in consecutive rounds, and
repeating an opponent at all.

Typical results over 10 rounds: with 13+ players, **zero repeated
partnerships** and no back-to-back repeat opponents; with 8 players some
repeats are mathematically unavoidable (only 7 possible partners) but are
spread as evenly as possible.

## Files

| File | Purpose |
| --- | --- |
| `RR_pickle_picker.py` | The desktop GUI application (PyQt6) |
| `streamlit_app.py` | The web app (Streamlit) — same engine and exports |
| `scheduler.py` | Scheduling/optimisation engine (no GUI dependency) |
| `export.py` | Print, PDF, Excel and phone-friendly HTML export helpers |
| `requirements.txt` | Web-app dependencies for Streamlit Cloud |
| `.streamlit/config.toml` | Streamlit theme (green accent) |
| `test_scheduler.py` | Engine tests: structure, bye fairness, optimisation quality |
| `test_export.py` | PDF/Excel export tests |
| `test_gui.py` | Desktop GUI smoke tests (run headless) |
| `test_streamlit_app.py` | Web app smoke tests (headless AppTest) |
| `players.txt` | Your saved roster (created after first player is added) |
