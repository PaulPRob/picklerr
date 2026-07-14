#!/usr/bin/env python3
"""RR_pickle_picker - pickleball round-robin scheduler GUI.

Run with:  python RR_pickle_picker.py

Left panel: manage the player roster (persisted to players.txt next to
this script) and tick who is playing today.  Choose the number of rounds
and hit "Generate Schedule"; each round appears as a tab showing the
courts, with that round's byes listed to the side.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import export
import scheduler
from scheduler import compute_stats, generate_schedule, num_byes, num_courts

PLAYERS_FILE = Path(__file__).with_name("players.txt")


class PicklePicker(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RR_pickle_picker")
        self.resize(1100, 700)
        self.current_schedule = None

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_side_panel())
        splitter.addWidget(self._build_schedule_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self._load_players()
        self._update_counts()

    # ------------------------------------------------------------------
    # Side panel: roster, attendance checkboxes, rounds, generate
    # ------------------------------------------------------------------
    def _build_side_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        title = QLabel("Players")
        title.setFont(QFont("", 14, QFont.Weight.Bold))
        layout.addWidget(title)

        entry_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Enter player name…")
        self.name_edit.returnPressed.connect(self._add_player)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_player)
        entry_row.addWidget(self.name_edit)
        entry_row.addWidget(add_btn)
        layout.addLayout(entry_row)

        self.player_list = QListWidget()
        self.player_list.itemChanged.connect(self._update_counts)
        layout.addWidget(self.player_list, stretch=1)

        btn_row = QHBoxLayout()
        for label, slot in (("All", self._check_all),
                            ("None", self._check_none),
                            ("Remove", self._remove_selected)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        rounds_row = QHBoxLayout()
        rounds_row.addWidget(QLabel("Rounds:"))
        self.rounds_spin = QSpinBox()
        self.rounds_spin.setRange(1, 40)
        self.rounds_spin.setValue(scheduler.DEFAULT_ROUNDS)
        rounds_row.addWidget(self.rounds_spin)
        rounds_row.addStretch()
        layout.addLayout(rounds_row)

        self.counts_label = QLabel()
        self.counts_label.setWordWrap(True)
        layout.addWidget(self.counts_label)

        self.generate_btn = QPushButton("Generate Schedule")
        self.generate_btn.setFont(QFont("", 12, QFont.Weight.Bold))
        self.generate_btn.clicked.connect(self._generate)
        layout.addWidget(self.generate_btn)

        export_row = QHBoxLayout()
        self.print_btn = QPushButton("Print…")
        self.print_btn.clicked.connect(self._print_schedule)
        self.pdf_btn = QPushButton("PDF…")
        self.pdf_btn.clicked.connect(self._export_pdf)
        self.excel_btn = QPushButton("Excel…")
        self.excel_btn.clicked.connect(self._export_excel)
        self.html_btn = QPushButton("Phone (HTML)…")
        self.html_btn.clicked.connect(self._export_html)
        for b in (self.print_btn, self.pdf_btn, self.excel_btn):
            b.setEnabled(False)
            export_row.addWidget(b)
        layout.addLayout(export_row)
        self.html_btn.setEnabled(False)
        layout.addWidget(self.html_btn)

        panel.setMinimumWidth(260)
        panel.setMaximumWidth(340)
        return panel

    def _build_schedule_panel(self) -> QWidget:
        self.tabs = QTabWidget()
        placeholder = QLabel(
            "Tick today's players on the left, set the number of rounds,\n"
            "then press “Generate Schedule”.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tabs.addTab(placeholder, "Welcome")
        return self.tabs

    # ------------------------------------------------------------------
    # Roster persistence
    # ------------------------------------------------------------------
    def _load_players(self) -> None:
        if PLAYERS_FILE.exists():
            for name in PLAYERS_FILE.read_text().splitlines():
                name = name.strip()
                if name:
                    self._append_player_item(name, checked=True)

    def _save_players(self) -> None:
        names = [self.player_list.item(i).text()
                 for i in range(self.player_list.count())]
        PLAYERS_FILE.write_text("\n".join(names) + ("\n" if names else ""))

    def _append_player_item(self, name: str, checked: bool) -> None:
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked
                           else Qt.CheckState.Unchecked)
        self.player_list.addItem(item)

    def _add_player(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            return
        existing = {self.player_list.item(i).text().lower()
                    for i in range(self.player_list.count())}
        if name.lower() in existing:
            QMessageBox.warning(self, "Duplicate",
                                f"“{name}” is already in the list.")
            return
        if self.player_list.count() >= scheduler.MAX_PLAYERS:
            QMessageBox.warning(
                self, "Roster full",
                f"Maximum of {scheduler.MAX_PLAYERS} players.")
            return
        self._append_player_item(name, checked=True)
        self.name_edit.clear()
        self._save_players()
        self._update_counts()

    def _remove_selected(self) -> None:
        for item in self.player_list.selectedItems():
            self.player_list.takeItem(self.player_list.row(item))
        self._save_players()
        self._update_counts()

    def _set_all_checks(self, state: Qt.CheckState) -> None:
        for i in range(self.player_list.count()):
            self.player_list.item(i).setCheckState(state)
        self._update_counts()

    def _check_all(self) -> None:
        self._set_all_checks(Qt.CheckState.Checked)

    def _check_none(self) -> None:
        self._set_all_checks(Qt.CheckState.Unchecked)

    def _checked_players(self) -> list[str]:
        return [self.player_list.item(i).text()
                for i in range(self.player_list.count())
                if self.player_list.item(i).checkState()
                == Qt.CheckState.Checked]

    def _update_counts(self) -> None:
        n = len(self._checked_players())
        if n == 0:
            self.counts_label.setText("No players ticked.")
        else:
            courts, byes = num_courts(n), num_byes(n)
            self.counts_label.setText(
                f"<b>{n} playing</b> → {courts} court"
                f"{'s' if courts != 1 else ''}, {byes} bye"
                f"{'s' if byes != 1 else ''} per round")

    # ------------------------------------------------------------------
    # Schedule generation and display
    # ------------------------------------------------------------------
    def _generate(self) -> None:
        players = self._checked_players()
        if not scheduler.MIN_PLAYERS <= len(players) <= scheduler.MAX_PLAYERS:
            QMessageBox.warning(
                self, "Cannot schedule",
                f"Tick between {scheduler.MIN_PLAYERS} and "
                f"{scheduler.MAX_PLAYERS} players (currently "
                f"{len(players)}).")
            return
        rounds = self.rounds_spin.value()
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Optimising…")
        QApplication.processEvents()
        try:
            schedule = generate_schedule(players, rounds)
        finally:
            self.generate_btn.setEnabled(True)
            self.generate_btn.setText("Generate Schedule")
        self._show_schedule(schedule)

    def _show_schedule(self, schedule) -> None:
        self.current_schedule = schedule
        for b in (self.print_btn, self.pdf_btn, self.excel_btn,
                  self.html_btn):
            b.setEnabled(True)
        self.tabs.clear()
        for rnd in schedule.rounds:
            self.tabs.addTab(self._round_tab(rnd), f"Round {rnd.number}")
        self.tabs.addTab(self._summary_tab(schedule), "Summary")

    def _round_tab(self, rnd) -> QWidget:
        tab = QWidget()
        outer = QHBoxLayout(tab)

        courts_box = QVBoxLayout()
        for i, match in enumerate(rnd.matches, start=1):
            group = QGroupBox(f"Court {i}")
            g = QVBoxLayout(group)
            lbl = QLabel(
                f"<span style='font-size:13pt'>"
                f"<b>{match.team1[0]} &amp; {match.team1[1]}</b>"
                f" &nbsp;vs&nbsp; "
                f"<b>{match.team2[0]} &amp; {match.team2[1]}</b></span>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            g.addWidget(lbl)
            courts_box.addWidget(group)
        courts_box.addStretch()

        courts_widget = QWidget()
        courts_widget.setLayout(courts_box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(courts_widget)
        outer.addWidget(scroll, stretch=3)

        bye_group = QGroupBox("Byes")
        bye_layout = QVBoxLayout(bye_group)
        if rnd.byes:
            for name in rnd.byes:
                bye_layout.addWidget(QLabel(f"⏸ {name}"))
        else:
            bye_layout.addWidget(QLabel("None"))
        bye_layout.addStretch()
        outer.addWidget(bye_group, stretch=1)
        return tab

    def _summary_tab(self, schedule) -> QWidget:
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
        repeats = [(sorted(pair), n)
                   for pair, n in stats.partner_counts.items() if n > 1]
        if repeats:
            lines.append("")
            lines.append("Repeated partnerships:")
            for (a, b), n in sorted(repeats):
                lines.append(f"  {a} & {b}: {n} times")
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n".join(lines))
        return text

    # ------------------------------------------------------------------
    # Print and export
    # ------------------------------------------------------------------
    def _print_schedule(self) -> None:
        if self.current_schedule is None:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QPrintDialog.DialogCode.Accepted:
            export.print_schedule(self.current_schedule, printer)

    def _export_pdf(self) -> None:
        if self.current_schedule is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export schedule as PDF", "pickleball_schedule.pdf",
            "PDF files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            export.export_pdf(self.current_schedule, path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Exported", f"Saved to:\n{path}")

    def _export_html(self) -> None:
        if self.current_schedule is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export phone-friendly draw",
            "pickleball_draw.html", "Web pages (*.html)")
        if not path:
            return
        if not path.lower().endswith((".html", ".htm")):
            path += ".html"
        try:
            export.export_html(self.current_schedule, path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(
            self, "Exported",
            f"Saved to:\n{path}\n\nSend this file to phones "
            "(WhatsApp, email, cloud drive) and open it in the "
            "phone's browser.")

    def _export_excel(self) -> None:
        if self.current_schedule is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export schedule as Excel", "pickleball_schedule.xlsx",
            "Excel workbooks (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            export.export_excel(self.current_schedule, path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Exported", f"Saved to:\n{path}")


def main() -> None:
    app = QApplication(sys.argv)
    window = PicklePicker()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
