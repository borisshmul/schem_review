"""Check selection panel — scrollable toggle list."""
from __future__ import annotations

import curses
from typing import Dict, List, Optional, Set

# Color pair IDs — must match app.py
_CP_SEL    = 3
_CP_CHK_ON = 10
_CP_ACCENT = 19
_CP_INFO   = 7


class CheckPicker:
    """Panel for enabling / disabling individual checks."""

    def __init__(self) -> None:
        self._checks: List[Dict] = []
        self.enabled: Set[str] = set()
        self.cursor: int = 0
        self.scroll: int = 0

    # ── Data ──────────────────────────────────────────────────────────────────

    def load_checks(self, checks: List[Dict]) -> None:
        self._checks = checks
        self.enabled = {c["name"] for c in checks}
        self.cursor = 0
        self.scroll = 0

    @property
    def enabled_checks(self) -> Set[str]:
        return self.enabled

    # ── Key handling ──────────────────────────────────────────────────────────

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

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, win: "curses.window") -> None:
        win.erase()
        h, w = win.getmaxyx()
        if h < 2 or w < 10:
            return

        # Row 0: summary
        n_on = len(self.enabled)
        n_tot = len(self._checks)
        summary = f" {n_on}/{n_tot} checks enabled"
        try:
            win.attron(curses.color_pair(_CP_ACCENT))
            win.addnstr(0, 0, summary, w - 1)
            win.attroff(curses.color_pair(_CP_ACCENT))
        except curses.error:
            pass

        list_h = h - 1
        if list_h < 1 or not self._checks:
            return

        # Scroll adjustment
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
            cat = chk.get("category", "DRC")
            desc = chk.get("description", "")
            is_on = name in self.enabled
            is_cur = idx == self.cursor

            status = "[\u2713]" if is_on else "[ ]"

            if w >= 52:
                cat_w = 4
                name_w = min(22, max(8, w - cat_w - 12))
                desc_w = max(4, w - cat_w - name_w - 12)
                line = (
                    f"  {status} {cat[:cat_w]:<{cat_w}}  "
                    f"{name[:name_w]:<{name_w}}  {desc[:desc_w]}"
                )
            elif w >= 28:
                name_w = max(6, w - 10)
                line = f"  {status}  {name[:name_w]}"
            else:
                line = f" {status} {name[:w - 6]}"

            try:
                if is_cur:
                    win.attron(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                elif is_on:
                    win.attron(curses.color_pair(_CP_CHK_ON))
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(curses.color_pair(_CP_CHK_ON))
                else:
                    win.attron(curses.A_DIM)
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(curses.A_DIM)
            except curses.error:
                pass
