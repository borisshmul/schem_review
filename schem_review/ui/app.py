"""Top-level curses application — Texas-themed split-panel design."""
from __future__ import annotations

import curses
import itertools
import time
from pathlib import Path
from typing import List, Optional

from schem_review import __version__
from schem_review.checks import get_all_checks, run_checks
from schem_review.confidence import apply_confidence_filter
from schem_review.model import Finding, Netlist
from schem_review.output import write_log, write_md
from schem_review.parser import ParseError, parse_file
from schem_review.ui.check_picker import CheckPicker
from schem_review.ui.file_picker import FilePicker
from schem_review.ui.results_view import ResultsView

# ── 8-bit armadillo animation ─────────────────────────────────────────────────
# Each frame = 7 rows: [top, head, shell1, shell2, bottom, legs, ground-fx]

_AF_TOP = " .-------. "
_AF_BOT = " '-------' "
_AF_SH1 = " |▓░▓░▓░▓| "
_AF_SH2 = " |░▓░▓░▓░| "

_AH_NORM = "(o  ^^  o)>"   # normal
_AH_BLNK = "(-  ^^  -)>"   # blink
_AH_SQNT = "(>  ^^  <)>"   # pre-jump squint
_AH_SURP = "(O  !!  O)>"   # surprised / airborne
_AH_PEAK = "(*  **  *)>"   # peak of jump
_AH_WOBB = "(~  ^^  ~)>"   # wobbly/happy wiggle

_AL_IDLE = "  ▐▌  ▐▌  "   # standing
_AL_WLK0 = " /▐▌  ▐▌  "   # left leg forward
_AL_WLK1 = "  ▐▌  ▐▌\\ "   # right leg forward
_AL_CRCH = "  \\▌▌/    "   # crouch before jump
_AL_AIR  = "   \\/     "   # airborne
_AL_PEAK = "    ^     "    # at peak (tucked)
_AL_LAND = " *▌  ▌*   "   # landing impact


def _af(head: str, legs: str, gnd: str = "") -> List[str]:
    return [_AF_TOP, head, _AF_SH1, _AF_SH2, _AF_BOT, legs, gnd]


_ARMI_IDLE_FRAMES: List[List[str]] = [
    _af(_AH_NORM, _AL_IDLE),
    _af(_AH_NORM, _AL_IDLE),
    _af(_AH_NORM, _AL_IDLE),
    _af(_AH_NORM, _AL_IDLE),
    _af(_AH_BLNK, _AL_IDLE),          # blink
    _af(_AH_NORM, _AL_IDLE),
    _af(_AH_NORM, _AL_IDLE),
    _af(_AH_NORM, _AL_IDLE),
    _af(_AH_NORM, _AL_IDLE),
    _af(_AH_WOBB, _AL_IDLE),          # happy wiggle
    _af(_AH_NORM, _AL_IDLE),
    _af(_AH_NORM, _AL_IDLE),
]

_ARMI_WALK_FRAMES: List[List[str]] = [
    _af(_AH_NORM, _AL_WLK0),
    _af(_AH_NORM, _AL_IDLE),
    _af(_AH_NORM, _AL_WLK1),
    _af(_AH_NORM, _AL_IDLE),
]

_ARMI_JUMP_FRAMES: List[List[str]] = [
    _af(_AH_SQNT, _AL_CRCH),                      # squat/prep
    _af(_AH_SURP, _AL_AIR),                       # launch
    _af(_AH_SURP, _AL_AIR,  "  ~ ~ ~   "),        # rising
    _af(_AH_PEAK, _AL_PEAK, "* * * * * "),        # peak — stars!
    _af(_AH_SURP, _AL_AIR),                       # falling
    _af(_AH_SURP, _AL_LAND, "~ ~ ~ ~ ~ "),        # impact dust
    _af(_AH_BLNK, _AL_IDLE, "  . . .   "),        # dazed
    _af(_AH_NORM, _AL_IDLE),                      # recover
]

# Bigger static art for the splash screen only
_ARMI_SPLASH_ART = [
    "   .----------.  ",
    "  (o   ^^^^   o)>",
    "  |▓░|▓░|▓░|▓░|  ",
    "  |░▓|░▓|░▓|░▓|  ",
    "  |▓░|▓░|▓░|▓░|  ",
    "   '----------'  ",
    "    ▐▌       ▐▌  ",
]
_ARMI_SPLASH_LINES = [
    "Hi! I'm Armi,",
    "your Texas",
    "schematic review",
    "armadillo!",
    "",
    '"Check yo nets,',
    ' pardner!"',
]

# ── Color pair IDs ────────────────────────────────────────────────────────────
_CP_NORMAL       = 1
_CP_HEADER       = 2
_CP_SEL          = 3
_CP_TAB_ACT      = 4
_CP_ERR          = 5
_CP_WARN         = 6
_CP_INFO         = 7
_CP_STATUS       = 8
_CP_DIM          = 9
_CP_CHK_ON       = 10
_CP_CHK_OFF      = 11
_CP_SECT         = 12
_CP_RUN_RDY      = 13
_CP_RUN_DIM      = 14
_CP_RUN_FOCUS    = 15
_CP_DIR          = 16
_CP_FILE_OK      = 17
_CP_PROG_FILL    = 18
_CP_ACCENT       = 19
_CP_BORDER_ACT   = 20
_CP_BORDER_INACT = 21
_CP_TAB_INACT    = 22

_TAB_SETUP   = 0
_TAB_RESULTS = 1
_FOCUS_FILES  = 0
_FOCUS_CHECKS = 1

_ARMI_PANEL_H = 11   # rows reserved for Armi on SETUP tab (below checks)
_ARMI_PANEL_W = 36   # cols reserved for Armi on RESULTS tab (right column)


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(_CP_NORMAL,       curses.COLOR_WHITE,   -1)
    curses.init_pair(_CP_HEADER,       curses.COLOR_BLACK,   curses.COLOR_CYAN)
    curses.init_pair(_CP_SEL,          curses.COLOR_BLACK,   curses.COLOR_WHITE)
    curses.init_pair(_CP_TAB_ACT,      curses.COLOR_BLACK,   curses.COLOR_CYAN)
    curses.init_pair(_CP_ERR,          curses.COLOR_RED,     -1)
    curses.init_pair(_CP_WARN,         curses.COLOR_YELLOW,  -1)
    curses.init_pair(_CP_INFO,         curses.COLOR_CYAN,    -1)
    curses.init_pair(_CP_STATUS,       curses.COLOR_BLACK,   curses.COLOR_WHITE)
    curses.init_pair(_CP_DIM,          curses.COLOR_WHITE,   -1)
    curses.init_pair(_CP_CHK_ON,       curses.COLOR_GREEN,   -1)
    curses.init_pair(_CP_CHK_OFF,      curses.COLOR_RED,     -1)
    curses.init_pair(_CP_SECT,         curses.COLOR_CYAN,    -1)
    curses.init_pair(_CP_RUN_RDY,      curses.COLOR_BLACK,   curses.COLOR_GREEN)
    curses.init_pair(_CP_RUN_DIM,      curses.COLOR_WHITE,   -1)
    curses.init_pair(_CP_RUN_FOCUS,    curses.COLOR_BLACK,   curses.COLOR_GREEN)
    curses.init_pair(_CP_DIR,          curses.COLOR_CYAN,    -1)
    curses.init_pair(_CP_FILE_OK,      curses.COLOR_GREEN,   -1)
    curses.init_pair(_CP_PROG_FILL,    curses.COLOR_BLACK,   curses.COLOR_GREEN)
    curses.init_pair(_CP_ACCENT,       curses.COLOR_YELLOW,  -1)
    curses.init_pair(_CP_BORDER_ACT,   curses.COLOR_CYAN,    -1)
    curses.init_pair(_CP_BORDER_INACT, curses.COLOR_WHITE,   -1)
    curses.init_pair(_CP_TAB_INACT,    curses.COLOR_WHITE,   -1)


_HELP_TEXT = """\
schem_review  keyboard shortcuts
─────────────────────────────────────────
  1 / 2        Switch to SETUP / RESULTS
  Tab          Switch focus between panels
  R            Run checks (from any screen)
  Q            Quit
  F1           This help
  F2           Toggle Armi mascot panel
  !            Secret easter egg ;)

  FILES panel (left, SETUP tab)
    Up/Down      Navigate entries
    Enter / →    Open dir or select file
    ← / Backsp   Go up to parent directory
    PgUp/PgDn    Scroll quickly
    /            Search — type to filter
    Esc          Clear search filter

  CHECKS panel (right, SETUP tab)
    Up/Down      Navigate check list
    Space        Toggle check on / off
    A            Select ALL checks
    N            Deselect ALL checks

  RESULTS tab
    Up/Down      Navigate findings
    Enter        Expand / collapse section
    PgUp/PgDn    Scroll quickly
    /            Search findings
    Esc          Clear search filter
    Query syntax:  error|warn  (OR)
                   net&open    (AND)
                   power*flag  (wildcard)

Press any key to close.
"""


class App:
    """Main curses application."""

    def __init__(self, stdscr: "curses.window") -> None:
        self.stdscr = stdscr
        self.current_tab: int = _TAB_SETUP
        self.setup_focus: int = _FOCUS_FILES
        self.status_msg: str = (
            "Step 1: pick a file  \u203a  Step 2: select checks  \u203a  Step 3: press [R]"
        )
        self.netlist: Optional[Netlist] = None
        self.findings: List[Finding] = []
        self.last_log: Optional[Path] = None
        self.last_md: Optional[Path] = None
        self.show_armi: bool = True

        # Animation state
        self._anim_tick: int = 0
        self._armi_state: str = "idle"   # "idle" | "jump"
        self._jump_frame_idx: int = 0

        self.file_picker = FilePicker()
        self.check_picker = CheckPicker()
        self.results_view = ResultsView()

        _init_colors()
        curses.curs_set(0)
        self.stdscr.keypad(True)

        checks = get_all_checks()
        self.check_picker.load_checks(checks)

        self._h = 0
        self._w = 0
        self._recalc_layout()
        self._show_splash()

    # ── Animation ─────────────────────────────────────────────────────────────

    def _trigger_jump(self) -> None:
        self._armi_state = "jump"
        self._jump_frame_idx = 0

    def _get_armi_frame(self) -> List[str]:
        if self._armi_state == "jump":
            idx = min(self._jump_frame_idx, len(_ARMI_JUMP_FRAMES) - 1)
            return _ARMI_JUMP_FRAMES[idx]
        if not self.file_picker.selected_file:
            # Walk animation while exploring files
            idx = (self._anim_tick // 2) % len(_ARMI_WALK_FRAMES)
            return _ARMI_WALK_FRAMES[idx]
        # Idle blink when file is picked
        idx = (self._anim_tick // 3) % len(_ARMI_IDLE_FRAMES)
        return _ARMI_IDLE_FRAMES[idx]

    # ── Layout ────────────────────────────────────────────────────────────────

    def _recalc_layout(self) -> None:
        self._h, self._w = self.stdscr.getmaxyx()

    def _panel_dims(self) -> tuple:
        h = max(1, self._h - 3)
        return h, self._w, 2, 0

    def _split_dims(self) -> tuple:
        ph, pw, py, px = self._panel_dims()
        lw = max(10, (pw * 55) // 100)
        rw = max(10, pw - lw)
        return (ph, lw, py, px), (ph, rw, py, px + lw)

    # ── Splash ────────────────────────────────────────────────────────────────

    def _show_splash(self) -> None:
        h, w = self.stdscr.getmaxyx()
        if h < 8 or w < 30:
            return

        box_h = min(22, h - 2)
        box_w = min(62, w - 4)
        sy = max(0, (h - box_h) // 2)
        sx = max(0, (w - box_w) // 2)

        try:
            win = curses.newwin(box_h, box_w, sy, sx)
        except curses.error:
            return

        self.stdscr.nodelay(True)

        def _paint(bar_step: int) -> None:
            try:
                win.erase()
                win.attron(curses.color_pair(_CP_BORDER_ACT) | curses.A_BOLD)
                win.border()
                win.attroff(curses.color_pair(_CP_BORDER_ACT) | curses.A_BOLD)

                title = "  schem_review  "
                ver = f"  v{__version__}  "
                win.attron(curses.color_pair(_CP_HEADER) | curses.A_BOLD)
                win.addnstr(1, max(1, (box_w - len(title)) // 2), title, box_w - 2)
                win.attroff(curses.color_pair(_CP_HEADER) | curses.A_BOLD)
                win.attron(curses.color_pair(_CP_DIM))
                win.addnstr(2, max(1, (box_w - len(ver)) // 2), ver, box_w - 2)
                win.attroff(curses.color_pair(_CP_DIM))

                art_y, art_x = 4, 3
                for i, line in enumerate(_ARMI_SPLASH_ART):
                    if art_y + i >= box_h - 4:
                        break
                    win.attron(curses.color_pair(_CP_ACCENT) | curses.A_BOLD)
                    win.addnstr(art_y + i, art_x, line, box_w - art_x - 2)
                    win.attroff(curses.color_pair(_CP_ACCENT) | curses.A_BOLD)

                info_x = art_x + max(len(l) for l in _ARMI_SPLASH_ART) + 2
                if info_x < box_w - 10:
                    for i, line in enumerate(_ARMI_SPLASH_LINES):
                        row = art_y + i
                        if row >= box_h - 4:
                            break
                        win.attron(curses.color_pair(_CP_NORMAL))
                        win.addnstr(row, info_x, line, box_w - info_x - 2)
                        win.attroff(curses.color_pair(_CP_NORMAL))

                tag = "* Texas Schematic Design Review Tool *"
                tag_row = art_y + len(_ARMI_SPLASH_ART) + 1
                if tag_row < box_h - 3:
                    win.attron(curses.color_pair(_CP_ACCENT))
                    win.addnstr(tag_row, max(1, (box_w - len(tag)) // 2), tag, box_w - 2)
                    win.attroff(curses.color_pair(_CP_ACCENT))

                bar_row = box_h - 3
                if bar_row > tag_row:
                    bar_w = box_w - 10
                    filled = min(bar_w, int(bar_w * bar_step / 20))
                    bar = "\u2588" * filled + "\u2591" * (bar_w - filled)
                    pct = f"{min(100, int(bar_step * 5)):3d}%"
                    win.attron(curses.color_pair(_CP_PROG_FILL))
                    win.addnstr(bar_row, 3, f" [{bar}] {pct}", box_w - 4)
                    win.attroff(curses.color_pair(_CP_PROG_FILL))
                    lbl = "Loading checks..."
                    win.attron(curses.A_DIM)
                    win.addnstr(bar_row + 1, max(1, (box_w - len(lbl)) // 2), lbl, box_w - 2)
                    win.attroff(curses.A_DIM)

                win.refresh()
            except curses.error:
                pass

        for step in range(21):
            if self.stdscr.getch() != -1:
                break
            _paint(step)
            time.sleep(0.04)

        _paint(20)
        time.sleep(0.25)
        self.stdscr.nodelay(False)
        curses.flushinp()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_header(self) -> None:
        if self._h < 1:
            return
        shortcuts = "[F1]Help  [F2]Armi  [R]Run  [Q]Quit"
        left = f"  \u2605 schem_review {__version__}"
        quip = 'Armi sez: "Check yo nets, pardner!"'
        avail = self._w - len(left) - len(shortcuts) - 4
        mid = quip[:avail] if avail > 8 else ""
        pad = max(1, self._w - len(left) - len(mid) - len(shortcuts) - 1)
        line = left + " " * max(1, pad // 2) + mid + " " * max(1, pad - pad // 2) + shortcuts
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

        x = 1
        for label, idx in [("  SETUP  ", _TAB_SETUP), ("  RESULTS  ", _TAB_RESULTS)]:
            active = idx == self.current_tab
            try:
                if active:
                    self.stdscr.attron(curses.color_pair(_CP_TAB_ACT) | curses.A_BOLD)
                    self.stdscr.addnstr(1, x, label, self._w - x - 1)
                    self.stdscr.attroff(curses.color_pair(_CP_TAB_ACT) | curses.A_BOLD)
                else:
                    self.stdscr.attron(curses.color_pair(_CP_TAB_INACT) | curses.A_DIM)
                    self.stdscr.addnstr(1, x, label, self._w - x - 1)
                    self.stdscr.attroff(curses.color_pair(_CP_TAB_INACT) | curses.A_DIM)
            except curses.error:
                pass
            x += len(label) + 1

        ready = bool(self.file_picker.selected_file and self.check_picker.enabled)
        run_label = "  \u25b6  RUN  " if ready else "  \u25b7  RUN  "
        run_x = self._w - len(run_label) - 2
        if run_x > x + 2:
            try:
                attr = (
                    curses.color_pair(_CP_RUN_RDY) | curses.A_BOLD
                    if ready else
                    curses.color_pair(_CP_RUN_DIM) | curses.A_DIM
                )
                self.stdscr.attron(attr)
                self.stdscr.addnstr(1, run_x, run_label, self._w - run_x - 1)
                self.stdscr.attroff(attr)
            except curses.error:
                pass

    def _draw_status(self) -> None:
        if self._h < 1:
            return
        row = self._h - 1
        if self.file_picker.selected_file:
            file_part = f" \u25c4 {Path(self.file_picker.selected_file).name}"
        else:
            file_part = " (no file)"
        n_on = len(self.check_picker.enabled)
        n_tot = len(self.check_picker._checks)
        status = f"{file_part} \u2502 {n_on}/{n_tot} checks \u2502 {self.status_msg}"
        try:
            self.stdscr.attron(curses.color_pair(_CP_STATUS))
            self.stdscr.addnstr(row, 0, status.ljust(self._w), self._w - 1)
            self.stdscr.attroff(curses.color_pair(_CP_STATUS))
        except curses.error:
            pass

    def _draw_boxed_panel(self, y: int, x: int, h: int, w: int, title: str, active: bool) -> None:
        if h < 3 or w < 4:
            return
        try:
            bwin = curses.newwin(h, w, y, x)
            pair = _CP_BORDER_ACT if active else _CP_BORDER_INACT
            bwin.attron(curses.color_pair(pair) | (curses.A_BOLD if active else 0))
            bwin.border()
            bwin.attroff(curses.color_pair(pair) | (curses.A_BOLD if active else 0))
            t = f" {title} "
            if active:
                bwin.attron(curses.color_pair(_CP_TAB_ACT) | curses.A_BOLD)
            else:
                bwin.attron(curses.color_pair(_CP_BORDER_INACT) | curses.A_DIM)
            bwin.addnstr(0, 2, t, w - 4)
            if active:
                bwin.attroff(curses.color_pair(_CP_TAB_ACT) | curses.A_BOLD)
            else:
                bwin.attroff(curses.color_pair(_CP_BORDER_INACT) | curses.A_DIM)
            bwin.noutrefresh()
        except curses.error:
            pass

    def _draw_setup_tab(self) -> None:
        (lh, lw, ly, lx), (rh, rw, ry, rx) = self._split_dims()

        self._draw_boxed_panel(
            ly, lx, lh, lw,
            "FILES — \u2191\u2193 nav  \u21b5/\u2192 open  \u2190 up  / search",
            self.setup_focus == _FOCUS_FILES,
        )
        if lh > 2 and lw > 2:
            try:
                cwin = curses.newwin(lh - 2, lw - 2, ly + 1, lx + 1)
                self.file_picker.draw(cwin)
                cwin.noutrefresh()
            except curses.error:
                pass

        armi_h = _ARMI_PANEL_H if (self.show_armi and rh >= _ARMI_PANEL_H + 5) else 0
        checks_h = rh - armi_h

        self._draw_boxed_panel(
            ry, rx, checks_h, rw,
            "CHECKS — Space toggle  A all  N none",
            self.setup_focus == _FOCUS_CHECKS,
        )
        if checks_h > 2 and rw > 2:
            try:
                cwin = curses.newwin(checks_h - 2, rw - 2, ry + 1, rx + 1)
                self.check_picker.draw(cwin)
                cwin.noutrefresh()
            except curses.error:
                pass

        if armi_h > 0:
            self._draw_armi_panel(ry + checks_h, rx, armi_h, rw)

    def _draw_results_tab(self) -> None:
        ph, pw, py, px = self._panel_dims()
        if ph < 1 or pw < 1:
            return

        armi_w = _ARMI_PANEL_W if (self.show_armi and pw >= _ARMI_PANEL_W + 30) else 0
        results_w = pw - armi_w

        try:
            win = curses.newwin(ph, results_w, py, px)
            self.results_view.draw(win)
            win.noutrefresh()
        except curses.error:
            pass

        if armi_w > 0:
            self._draw_armi_panel(py, px + results_w, ph, armi_w)

    # ── Armi panel ────────────────────────────────────────────────────────────

    def _armi_tips(self) -> List[str]:
        if not self.file_picker.selected_file:
            return [
                "How to pick a file:",
                "",
                "1. Tab \u2192 FILES",
                "2. \u2191\u2193 navigate",
                "3. \u21b5 or \u2192",
                "   open a dir",
                "4. \u21b5 on .xml",
                "   or .hkp",
                "   to select",
                "",
                "Then [R] to run!",
            ]
        if self.netlist is None:
            name = Path(self.file_picker.selected_file).name
            short = (name[:10] + "..") if len(name) > 12 else name
            n_on = len(self.check_picker.enabled)
            return [
                f"\u2605 {short}",
                f"  {n_on} checks on",
                "",
                "Tab \u2192 CHECKS",
                "Space toggle",
                "A = select all",
                "",
                "Press [R]",
                "to run!",
                "",
                "Yeehaw! \u2605",
            ]
        errs = sum(1 for f in self.findings if f.severity.value == "ERROR")
        wrns = sum(1 for f in self.findings if f.severity.value == "WARN")
        infs = sum(1 for f in self.findings if f.severity.value == "INFO")
        return [
            f"{len(self.findings)} findings:",
            f"  \u2718 {errs} errors",
            f"  \u26a0 {wrns} warnings",
            f"  \u2139 {infs} info",
            "",
            "Press [2] for",
            "RESULTS tab.",
            "",
            "Great work! \u2605",
        ]

    def _draw_armi_panel(self, y: int, x: int, h: int, w: int) -> None:
        if h < 4 or w < 10:
            return
        try:
            win = curses.newwin(h, w, y, x)
            win.attron(curses.color_pair(_CP_ACCENT))
            win.border()
            title = " ARMI [F2] "
            win.addnstr(0, max(1, (w - len(title)) // 2), title, w - 2)
            win.attroff(curses.color_pair(_CP_ACCENT))

            frame = self._get_armi_frame()
            tips = self._armi_tips()
            inner_h = h - 2
            inner_w = w - 2
            art_w = max(len(ln) for ln in frame[:6])

            # Row color config: shell rows get DIM so shell chars pop
            _row_style = [
                (_CP_ACCENT, curses.A_BOLD),   # 0 top
                (_CP_ACCENT, curses.A_BOLD),   # 1 head
                (_CP_ACCENT, 0),               # 2 shell1
                (_CP_ACCENT, 0),               # 3 shell2
                (_CP_ACCENT, curses.A_BOLD),   # 4 bottom
                (_CP_NORMAL, 0),               # 5 legs
                (_CP_INFO,   curses.A_BOLD),   # 6 ground fx
            ]

            if inner_w >= art_w + 8:
                # Side-by-side: art left, tips right
                tip_x = art_w + 3
                avail_tip_w = max(4, inner_w - tip_x - 1)
                for i, line in enumerate(frame):
                    row = i + 1
                    if row > inner_h:
                        break
                    cp, bold = _row_style[i] if i < len(_row_style) else (_CP_NORMAL, 0)
                    try:
                        win.attron(curses.color_pair(cp) | bold)
                        win.addnstr(row, 1, line, art_w + 2)
                        win.attroff(curses.color_pair(cp) | bold)
                    except curses.error:
                        pass
                tip_row = 1
                for tip in tips:
                    if tip_row > inner_h:
                        break
                    if tip:
                        try:
                            win.attron(curses.color_pair(_CP_NORMAL))
                            win.addnstr(tip_row, tip_x, tip[:avail_tip_w], avail_tip_w)
                            win.attroff(curses.color_pair(_CP_NORMAL))
                        except curses.error:
                            pass
                    tip_row += 1
            else:
                # Stacked: art top, tips below
                for i, line in enumerate(frame):
                    row = i + 1
                    if row > inner_h:
                        break
                    cp, bold = _row_style[i] if i < len(_row_style) else (_CP_NORMAL, 0)
                    try:
                        win.attron(curses.color_pair(cp) | bold)
                        win.addnstr(row, 1, line[:inner_w], inner_w)
                        win.attroff(curses.color_pair(cp) | bold)
                    except curses.error:
                        pass
                tip_row = len(frame) + 1
                for tip in tips:
                    if tip_row > inner_h:
                        break
                    if tip:
                        try:
                            win.attron(curses.color_pair(_CP_NORMAL))
                            win.addnstr(tip_row, 1, tip[:inner_w], inner_w)
                            win.attroff(curses.color_pair(_CP_NORMAL))
                        except curses.error:
                            pass
                    tip_row += 1

            win.noutrefresh()
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
        # Must noutrefresh stdscr first — panel windows paint on top
        try:
            self.stdscr.noutrefresh()
        except curses.error:
            pass
        if self.current_tab == _TAB_SETUP:
            self._draw_setup_tab()
        else:
            self._draw_results_tab()
        try:
            curses.doupdate()
        except curses.error:
            pass

    # ── Key handling ──────────────────────────────────────────────────────────

    def _handle_key(self, key: int) -> bool:
        # File picker gets absolute priority when its search bar is active —
        # every key (including q/Q/r/R/1/2) is typed into the bar.
        if (self.current_tab == _TAB_SETUP
                and self.setup_focus == _FOCUS_FILES
                and self.file_picker.search_active):
            action = self.file_picker.handle_key(key)
            if action == "file_selected":
                self._on_file_selected()
            return True

        # Hard globals — only reachable when search bar is not active
        if key in (ord("q"), ord("Q")):
            return False

        if key == curses.KEY_F1:
            self._show_help()
            return True

        if key == curses.KEY_F2:
            self.show_armi = not self.show_armi
            return True

        # App shortcuts
        # Easter egg — ! makes Armi jump
        if key == ord("!"):
            self._trigger_jump()
            return True

        if key == ord("1"):
            self.current_tab = _TAB_SETUP
            return True
        if key == ord("2"):
            self.current_tab = _TAB_RESULTS
            return True

        if key in (ord("r"), ord("R")):
            self._run()
            return True

        if key == ord("\t"):
            if self.current_tab == _TAB_SETUP:
                self.setup_focus = 1 - self.setup_focus
            else:
                self.current_tab = 1 - self.current_tab
            return True

        if key == curses.KEY_LEFT:
            if self.current_tab == _TAB_SETUP and self.setup_focus == _FOCUS_FILES:
                self.file_picker.handle_key(key)
            else:
                self.current_tab = max(0, self.current_tab - 1)
            return True

        if key == curses.KEY_RIGHT:
            if self.current_tab == _TAB_SETUP and self.setup_focus == _FOCUS_FILES:
                action = self.file_picker.handle_key(key)
                if action == "file_selected":
                    self._on_file_selected()
            else:
                self.current_tab = min(_TAB_RESULTS, self.current_tab + 1)
            return True

        if self.current_tab == _TAB_SETUP:
            if self.setup_focus == _FOCUS_FILES:
                action = self.file_picker.handle_key(key)
                if action == "file_selected":
                    self._on_file_selected()
            else:
                # Easter egg: A (select all) triggers jump
                if key in (ord("a"), ord("A")):
                    self._trigger_jump()
                self.check_picker.handle_key(key)
        else:
            self.results_view.handle_key(key)

        return True

    def _on_file_selected(self) -> None:
        fp = self.file_picker.selected_file
        if fp:
            self.status_msg = "File ready \u2014 Tab to CHECKS panel, then press [R] to run"
            self.setup_focus = _FOCUS_CHECKS
            self._trigger_jump()   # Armi celebrates every file pick!

    # ── Run ───────────────────────────────────────────────────────────────────

    def _draw_progress(self, n: int, total: int, label: str) -> None:
        row = self._h - 1
        w = self._w
        pct = n / max(1, total)
        bar_w = min(28, w // 4)
        filled = int(bar_w * pct)
        bar = "\u2588" * filled + "\u2591" * (bar_w - filled)
        text = f" [{bar}] {int(pct * 100):3d}%  {label}"
        try:
            self.stdscr.attron(curses.color_pair(_CP_STATUS))
            self.stdscr.addnstr(row, 0, text.ljust(w), w - 1)
            self.stdscr.attroff(curses.color_pair(_CP_STATUS))
            self.stdscr.noutrefresh()
            curses.doupdate()
        except curses.error:
            pass

    def _run(self) -> None:
        selected = self.file_picker.selected_file
        if not selected:
            self.status_msg = "No file selected \u2014 use FILES panel to pick a file"
            return
        enabled = list(self.check_picker.enabled_checks)
        if not enabled:
            self.status_msg = "No checks enabled \u2014 use CHECKS panel to enable at least one"
            return

        self._draw_progress(0, 1, "Parsing schematic...")
        try:
            self.netlist = parse_file(selected)
        except ParseError as exc:
            self.status_msg = f"Parse error: {exc}"
            return
        except Exception as exc:  # noqa: BLE001
            self.status_msg = f"Unexpected error: {exc}"
            return

        n_comps = len(self.netlist.components)
        n_nets = len(self.netlist.nets)
        total = len(enabled)
        counter = [0]
        spinner = itertools.cycle(r"|/-\\")

        def progress_cb(check_name: str) -> None:
            counter[0] += 1
            self._draw_progress(counter[0], total, f"{next(spinner)} {check_name}")

        self.findings = apply_confidence_filter(
            run_checks(self.netlist, enabled, progress_cb)
        )

        try:
            self.last_log = write_log(selected, self.findings)
            self.last_md = write_md(selected, self.findings)
        except Exception as exc:  # noqa: BLE001
            self.status_msg = f"Done: {len(self.findings)} findings  (output write failed: {exc})"
        else:
            log_name = self.last_log.name if self.last_log else "?"
            md_name = self.last_md.name if self.last_md else "?"
            self.status_msg = (
                f"Done: {len(self.findings)} findings "
                f"({n_comps} comps, {n_nets} nets) "
                f"\u2192 {log_name}  {md_name}"
            )

        # Easter egg: jump if no errors!
        errs = sum(1 for f in self.findings if f.severity.value == "ERROR")
        if errs == 0:
            self._trigger_jump()

        self.results_view.set_findings(self.findings)
        self.current_tab = _TAB_RESULTS

    # ── Help overlay ──────────────────────────────────────────────────────────

    def _show_help(self) -> None:
        lines = _HELP_TEXT.split("\n")
        h, w = self.stdscr.getmaxyx()
        box_h = min(len(lines) + 4, h - 2)
        box_w = min(max(len(ln) for ln in lines) + 6, w - 4)
        sy = max(0, (h - box_h) // 2)
        sx = max(0, (w - box_w) // 2)
        try:
            win = curses.newwin(box_h, box_w, sy, sx)
            win.attron(curses.color_pair(_CP_BORDER_ACT) | curses.A_BOLD)
            win.border()
            title = " Help \u2014 schem_review "
            win.addnstr(0, max(1, (box_w - len(title)) // 2), title, box_w - 2)
            win.attroff(curses.color_pair(_CP_BORDER_ACT) | curses.A_BOLD)

            for i, line in enumerate(lines[: box_h - 3]):
                try:
                    if line.startswith("  ") and not line.startswith("    "):
                        win.attron(curses.color_pair(_CP_INFO) | curses.A_BOLD)
                        win.addnstr(i + 1, 2, line, box_w - 4)
                        win.attroff(curses.color_pair(_CP_INFO) | curses.A_BOLD)
                    elif line.startswith("\u2500"):
                        win.attron(curses.color_pair(_CP_BORDER_ACT))
                        win.addnstr(i + 1, 2, line, box_w - 4)
                        win.attroff(curses.color_pair(_CP_BORDER_ACT))
                    else:
                        win.addnstr(i + 1, 2, line, box_w - 4)
                except curses.error:
                    pass

            close = "[ Press any key to close ]"
            try:
                win.attron(curses.A_DIM)
                win.addnstr(box_h - 2, max(1, (box_w - len(close)) // 2), close, box_w - 2)
                win.attroff(curses.A_DIM)
            except curses.error:
                pass

            win.refresh()
            win.getch()
        except curses.error:
            pass

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.stdscr.timeout(200)   # 200 ms tick → ~5 fps animation
        while True:
            try:
                self._recalc_layout()
                self._draw_all()
                key = self.stdscr.getch()

                if key == -1:
                    # Timeout tick: advance animation
                    self._anim_tick += 1
                    if self._armi_state == "jump":
                        self._jump_frame_idx += 1
                        if self._jump_frame_idx >= len(_ARMI_JUMP_FRAMES):
                            self._armi_state = "idle"
                            self._jump_frame_idx = 0
                    continue

                if key == curses.KEY_RESIZE:
                    self._recalc_layout()
                    continue

                if not self._handle_key(key):
                    break

            except KeyboardInterrupt:
                break
            except curses.error:
                pass
