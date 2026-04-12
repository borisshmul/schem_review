"""Top-level curses application — tab manager and run orchestrator."""
from __future__ import annotations

import curses
import itertools
import sys
from pathlib import Path
from typing import List, Optional

from schem_review import __version__
from schem_review.checks import get_all_checks, run_checks
from schem_review.model import Finding, Netlist
from schem_review.output import write_log, write_md
from schem_review.parser import ParseError, parse_file
from schem_review.ui.check_picker import CheckPicker
from schem_review.ui.file_picker import FilePicker
from schem_review.ui.results_view import ResultsView

_TITLE = f"schem_review v{__version__}"
_TAB_NAMES = ["1:Files", "2:Checks", "3:Results"]

# Tab bar also hosts a RUN button — index 3 in the focus ring
_TAB_RUN = 3  # virtual "tab" index for the RUN button

# Color pair indices
_CP_NORMAL   = 1   # default fg on default bg
_CP_HEADER   = 2   # header/status bar: white on blue
_CP_SELECTED = 3   # list selection: white on blue
_CP_TABACT   = 4   # active tab: black on white
_CP_ERROR    = 5   # severity ERROR: red
_CP_WARN     = 6   # severity WARN: yellow
_CP_INFO     = 7   # severity INFO: cyan
_CP_STATUS   = 8   # status bar: white on blue
_CP_DIM      = 9   # dimmed items
_CP_RUN_RDY  = 13  # run button — ready (green on black)
_CP_RUN_DIM  = 14  # run button — not ready (dim)
_CP_RUN_FOCUS = 15 # run button — focused


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(_CP_NORMAL,    curses.COLOR_WHITE,  -1)
    curses.init_pair(_CP_HEADER,    curses.COLOR_WHITE,  curses.COLOR_BLUE)
    curses.init_pair(_CP_SELECTED,  curses.COLOR_WHITE,  curses.COLOR_BLUE)
    curses.init_pair(_CP_TABACT,    curses.COLOR_BLACK,  curses.COLOR_WHITE)
    curses.init_pair(_CP_ERROR,     curses.COLOR_RED,    -1)
    curses.init_pair(_CP_WARN,      curses.COLOR_YELLOW, -1)
    curses.init_pair(_CP_INFO,      curses.COLOR_CYAN,   -1)
    curses.init_pair(_CP_STATUS,    curses.COLOR_WHITE,  curses.COLOR_BLUE)
    curses.init_pair(_CP_DIM,       curses.COLOR_WHITE,  -1)
    curses.init_pair(_CP_RUN_RDY,   curses.COLOR_GREEN,  -1)
    curses.init_pair(_CP_RUN_DIM,   curses.COLOR_WHITE,  -1)
    curses.init_pair(_CP_RUN_FOCUS, curses.COLOR_BLACK,  curses.COLOR_GREEN)


_HELP_TEXT = """\
schem_review — keyboard shortcuts
──────────────────────────────────────────────
  1 / 2 / 3   Switch to Files / Checks / Results tab
  Tab / ← →   Cycle tabs (→ also enters dirs in Files tab)
  R / ↵ RUN   Run selected checks on the loaded file
  Q           Quit
  F1          Show this help

  Tab 1 — Files
    ↑ ↓       Navigate directory listing
    → / ↵     Enter directory or select .xml / .hkp file
    ← / ⌫     Go up to parent directory
    PgUp/Dn   Scroll quickly

  Tab 2 — Checks
    ↑ ↓       Navigate check list
    Space      Toggle check on / off
    A          Select ALL checks
    N          Deselect ALL checks
    Navigate to [ RUN ] and press ↵, or press R from anywhere

  Tab 3 — Results
    ↑ ↓       Navigate results
    ↵         Collapse / expand severity section or finding detail
    PgUp/Dn   Scroll quickly

Press any key to close this help.
"""


class App:
    """Main curses application."""

    def __init__(self, stdscr: "curses.window") -> None:
        self.stdscr = stdscr
        # 0=Files  1=Checks  2=Results  3=RUN button (virtual)
        self.current_tab: int = 0
        self.status_msg: str = "Step 1: pick a file  →  Step 2: select checks  →  Step 3: press [ RUN ]"
        self.netlist: Optional[Netlist] = None
        self.findings: List[Finding] = []
        self.last_log: Optional[Path] = None
        self.last_md: Optional[Path] = None

        # Sub-panels
        self.file_picker = FilePicker()
        self.check_picker = CheckPicker()
        self.results_view = ResultsView()

        _init_colors()
        curses.curs_set(0)
        self.stdscr.keypad(True)

        # Load checks into the picker
        checks = get_all_checks()
        self.check_picker.load_checks(checks)

        # Pre-calculate layout
        self._h = 0
        self._w = 0
        self._panel_win: Optional["curses.window"] = None
        self._recalc_layout()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _recalc_layout(self) -> None:
        self._h, self._w = self.stdscr.getmaxyx()

    def _panel_dims(self) -> tuple:
        """Return (height, width, y, x) for the main content panel."""
        # Row 0: header, Row 1: tabbar, Row h-1: status
        h = max(1, self._h - 3)
        w = self._w
        return h, w, 2, 0

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw_header(self) -> None:
        if self._h < 1:
            return
        shortcuts = "[F1]Help  [R]Run  [Q]Quit"
        title_part = _TITLE
        gap = self._w - len(title_part) - len(shortcuts) - 2
        if gap < 1:
            gap = 1
        line = f" {title_part}{' ' * gap}{shortcuts}"
        try:
            self.stdscr.attron(curses.color_pair(_CP_HEADER) | curses.A_BOLD)
            self.stdscr.addnstr(0, 0, line.ljust(self._w), self._w - 1)
            self.stdscr.attroff(curses.color_pair(_CP_HEADER) | curses.A_BOLD)
        except curses.error:
            pass

    def _draw_tabbar(self) -> None:
        if self._h < 2:
            return
        try:
            self.stdscr.move(1, 0)
            self.stdscr.clrtoeol()
        except curses.error:
            pass

        # Draw the three content tabs
        x = 0
        for i, name in enumerate(_TAB_NAMES):
            label = f" {name} "
            active = i == self.current_tab
            try:
                if active:
                    self.stdscr.attron(curses.color_pair(_CP_TABACT) | curses.A_BOLD)
                else:
                    self.stdscr.attron(curses.A_NORMAL)
                self.stdscr.addnstr(1, x, label, self._w - x - 1)
                if active:
                    self.stdscr.attroff(curses.color_pair(_CP_TABACT) | curses.A_BOLD)
                else:
                    self.stdscr.attroff(curses.A_NORMAL)
            except curses.error:
                pass
            x += len(label) + 1

        # Draw the RUN button — right-aligned, styled by readiness
        run_label = "[ RUN ]"
        run_x = max(x + 2, self._w - len(run_label) - 2)
        if run_x >= self._w - 1:
            return
        ready = bool(self.file_picker.selected_file and self.check_picker.enabled)
        focused = self.current_tab == _TAB_RUN
        try:
            if focused:
                attr = curses.color_pair(_CP_RUN_FOCUS) | curses.A_BOLD
            elif ready:
                attr = curses.color_pair(_CP_RUN_RDY) | curses.A_BOLD
            else:
                attr = curses.color_pair(_CP_RUN_DIM) | curses.A_DIM
            self.stdscr.attron(attr)
            self.stdscr.addnstr(1, run_x, run_label, self._w - run_x - 1)
            self.stdscr.attroff(attr)
        except curses.error:
            pass

    def _draw_status(self) -> None:
        if self._h < 1:
            return
        row = self._h - 1
        file_part = ""
        if self.file_picker.selected_file:
            file_part = f" File: {Path(self.file_picker.selected_file).name} |"
        checks_part = f" {len(self.check_picker.enabled)} checks selected |"
        status = f"{file_part}{checks_part} {self.status_msg}"
        try:
            self.stdscr.attron(curses.color_pair(_CP_STATUS))
            self.stdscr.addnstr(row, 0, status.ljust(self._w), self._w - 1)
            self.stdscr.attroff(curses.color_pair(_CP_STATUS))
        except curses.error:
            pass

    def _draw_panel(self) -> None:
        ph, pw, py, px = self._panel_dims()
        if ph < 1 or pw < 1:
            return
        try:
            panel_win = curses.newwin(ph, pw, py, px)
        except curses.error:
            return

        panel = self._active_panel()
        try:
            panel.draw(panel_win)
            panel_win.noutrefresh()
        except curses.error:
            pass

    def _draw_all(self) -> None:
        try:
            self.stdscr.erase()
        except curses.error:
            pass
        self._draw_header()
        self._draw_tabbar()
        self._draw_status()
        self._draw_panel()
        try:
            curses.doupdate()
        except curses.error:
            pass

    def _draw_status_refresh(self) -> None:
        """Quick status-bar update used during long-running operations."""
        self._draw_status()
        try:
            self.stdscr.refresh()
        except curses.error:
            pass

    # ------------------------------------------------------------------
    # Panel routing
    # ------------------------------------------------------------------

    def _active_panel(self):
        if self.current_tab == 0:
            return self.file_picker
        if self.current_tab == 1:
            return self.check_picker
        if self.current_tab == 2:
            return self.results_view
        # _TAB_RUN (3) — no panel; draw the results view beneath
        return self.results_view

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

    def _handle_key(self, key: int) -> bool:  # noqa: C901
        """Return True to keep running, False to quit."""
        # ---- Global shortcuts -----------------------------------------
        if key in (ord("q"), ord("Q")):
            return False

        if key == curses.KEY_F1:
            self._show_help()
            return True

        # Numeric shortcuts always jump directly to a tab
        if key == ord("1"):
            self.current_tab = 0
            return True
        if key == ord("2"):
            self.current_tab = 1
            return True
        if key == ord("3"):
            self.current_tab = 2
            return True

        # R anywhere → run
        if key in (ord("r"), ord("R")):
            self._run()
            return True

        # Tab key cycles through tabs including the RUN button
        if key == ord("\t"):
            self.current_tab = (self.current_tab + 1) % (_TAB_RUN + 1)
            return True

        # Enter on the RUN button focus → run
        if self.current_tab == _TAB_RUN and key in (ord("\r"), ord("\n"), curses.KEY_ENTER):
            self._run()
            return True

        # ---- Arrow keys: Left/Right cycle tabs / move within panels ----
        if key == curses.KEY_LEFT:
            if self.current_tab == 0:
                # file_picker uses left to go up dir — delegate
                self.file_picker.handle_key(key)
            else:
                self.current_tab = max(0, self.current_tab - 1)
            return True

        if key == curses.KEY_RIGHT:
            if self.current_tab == 0:
                # file_picker uses right to enter dir / select — delegate
                action = self.file_picker.handle_key(key)
                if action == "file_selected":
                    fp = self.file_picker.selected_file
                    self.status_msg = f"File selected: {Path(fp).name}  — press [R] or navigate to [ RUN ]"
            else:
                self.current_tab = min(_TAB_RUN, self.current_tab + 1)
            return True

        # ---- RUN button focused: only meaningful keys above apply ------
        if self.current_tab == _TAB_RUN:
            return True

        # ---- Delegate to active panel ----------------------------------
        panel = self._active_panel()
        action = panel.handle_key(key)
        if action == "file_selected":
            fp = self.file_picker.selected_file
            self.status_msg = f"File selected: {Path(fp).name}  — press [R] or navigate to [ RUN ]"
        return True

    # ------------------------------------------------------------------
    # Run logic
    # ------------------------------------------------------------------

    def _run(self) -> None:
        selected = self.file_picker.selected_file
        if not selected:
            self.status_msg = "ERROR: No file selected — go to Tab 1 and choose a file"
            return

        enabled = list(self.check_picker.enabled_checks)
        if not enabled:
            self.status_msg = "ERROR: No checks enabled — go to Tab 2 and enable at least one"
            return

        # Parse
        self.status_msg = "Parsing file..."
        self._draw_status_refresh()

        try:
            self.netlist = parse_file(selected)
        except ParseError as exc:
            self.status_msg = f"Parse error: {exc}"
            return
        except Exception as exc:  # noqa: BLE001
            self.status_msg = f"Unexpected parse error: {exc}"
            return

        n_comps = len(self.netlist.components)
        n_nets = len(self.netlist.nets)
        self.status_msg = f"Parsed: {n_comps} components, {n_nets} nets — running checks..."
        self._draw_status_refresh()

        # Run checks with spinner
        spinner = itertools.cycle(r"|\-/")

        def progress_cb(check_name: str) -> None:
            spin = next(spinner)
            self.status_msg = f"Running [{spin}]: {check_name}"
            self._draw_status_refresh()

        self.findings = run_checks(self.netlist, enabled, progress_cb)

        # Write output files
        try:
            self.last_log = write_log(selected, self.findings)
            self.last_md = write_md(selected, self.findings)
        except Exception as exc:  # noqa: BLE001
            self.status_msg = (
                f"Run complete: {len(self.findings)} findings  "
                f"(output write failed: {exc})"
            )
        else:
            log_name = self.last_log.name if self.last_log else "?"
            md_name = self.last_md.name if self.last_md else "?"
            self.status_msg = (
                f"Done: {len(self.findings)} findings  "
                f"→ {log_name}  {md_name}"
            )

        # Switch to results tab
        self.results_view.set_findings(self.findings)
        self.current_tab = 2

    # ------------------------------------------------------------------
    # Help overlay
    # ------------------------------------------------------------------

    def _show_help(self) -> None:
        lines = _HELP_TEXT.split("\n")
        h, w = self.stdscr.getmaxyx()
        box_h = min(len(lines) + 2, h - 4)
        box_w = min(max(len(l) for l in lines) + 4, w - 4)
        start_y = (h - box_h) // 2
        start_x = (w - box_w) // 2

        try:
            win = curses.newwin(box_h, box_w, start_y, start_x)
            win.border()
            for i, line in enumerate(lines[:box_h - 2]):
                win.addnstr(i + 1, 2, line, box_w - 4)
            win.refresh()
            win.getch()
        except curses.error:
            pass

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        while True:
            try:
                self._recalc_layout()
                self._draw_all()
                key = self.stdscr.getch()
                if key == curses.KEY_RESIZE:
                    self._recalc_layout()
                    continue
                if not self._handle_key(key):
                    break
            except KeyboardInterrupt:
                break
            except curses.error:
                # Swallow curses errors (e.g., window too small during resize)
                pass
