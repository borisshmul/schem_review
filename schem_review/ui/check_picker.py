"""Check selection panel — scrollable toggle list of registered checks."""
from __future__ import annotations

import curses
from typing import Dict, List, Optional, Set


class CheckPicker:
    """Panel for enabling/disabling individual checks before a run."""

    PAIR_SELECTED = 3
    PAIR_ENABLED = 10
    PAIR_DISABLED = 11

    def __init__(self) -> None:
        # Populated after checks are imported
        self._checks: List[Dict] = []
        self.enabled: Set[str] = set()
        self.cursor: int = 0
        self.scroll: int = 0

    # ------------------------------------------------------------------

    def load_checks(self, checks: List[Dict]) -> None:
        """Set the available checks (list of registry dicts)."""
        self._checks = checks
        self.enabled = {c["name"] for c in checks}  # all enabled by default
        self.cursor = 0
        self.scroll = 0

    @property
    def enabled_checks(self) -> Set[str]:
        return self.enabled

    # ------------------------------------------------------------------

    def handle_key(self, key: int) -> Optional[str]:
        if not self._checks:
            return None

        if key == curses.KEY_UP:
            if self.cursor > 0:
                self.cursor -= 1
        elif key == curses.KEY_DOWN:
            if self.cursor < len(self._checks) - 1:
                self.cursor += 1
        elif key == ord(" "):
            name = self._checks[self.cursor]["name"]
            if name in self.enabled:
                self.enabled.discard(name)
            else:
                self.enabled.add(name)
        elif key in (ord("a"), ord("A")):
            self.enabled = {c["name"] for c in self._checks}
        elif key in (ord("n"), ord("N")):
            self.enabled = set()
        elif key == curses.KEY_PPAGE:
            self.cursor = max(0, self.cursor - 10)
        elif key == curses.KEY_NPAGE:
            self.cursor = min(len(self._checks) - 1, self.cursor + 10)
        return None

    # ------------------------------------------------------------------

    def draw(self, win: "curses.window") -> None:
        win.erase()
        h, w = win.getmaxyx()
        if h < 3 or w < 20:
            return

        # Header
        hdr = f"  {'#':>3}  {'St':2}  {'Cat':6}  {'Check name':<30}  Description"
        try:
            win.attron(curses.A_UNDERLINE)
            win.addnstr(0, 0, hdr, w - 1)
            win.attroff(curses.A_UNDERLINE)
        except curses.error:
            pass

        list_h = h - 2
        if list_h < 1 or not self._checks:
            return

        # Adjust scroll
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + list_h:
            self.scroll = self.cursor - list_h + 1

        for row_idx in range(list_h):
            idx = self.scroll + row_idx
            screen_row = row_idx + 1
            if idx >= len(self._checks):
                break

            chk = self._checks[idx]
            name = chk["name"]
            cat = chk.get("category", "DRC")[:6]
            desc = chk.get("description", "")
            is_enabled = name in self.enabled
            is_sel = idx == self.cursor

            status = "[x]" if is_enabled else "[ ]"
            desc_col_w = max(w - 48, 10)
            line = f"  {idx+1:>3}  {status}  {cat:<6}  {name:<30}  {desc[:desc_col_w]}"

            try:
                if is_sel:
                    win.attron(curses.color_pair(self.PAIR_SELECTED) | curses.A_BOLD)
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(curses.color_pair(self.PAIR_SELECTED) | curses.A_BOLD)
                elif is_enabled:
                    win.addnstr(screen_row, 0, line, w - 1)
                else:
                    win.attron(curses.A_DIM)
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(curses.A_DIM)
            except curses.error:
                pass

        # Footer hint
        hint = " ↑↓ navigate  Space toggle  A select-all  N deselect-all"
        try:
            win.attron(curses.A_DIM)
            win.addnstr(h - 1, 0, hint, w - 1)
            win.attroff(curses.A_DIM)
        except curses.error:
            pass
