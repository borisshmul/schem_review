"""Check selection panel — scrollable toggle list with category grouping and search."""
from __future__ import annotations

import curses
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

# Color pair IDs — must match app.py
_CP_SEL    = 3
_CP_CHK_ON = 10
_CP_ACCENT = 19
_CP_INFO   = 7
_CP_SECTION = 12

# Canonical display order for known categories
_CAT_ORDER = ["DRC", "EE", "SGMII", "RGMII", "MDI", "MDIO", "PWR"]


def _cat_sort_key(cat: str) -> Tuple[int, str]:
    try:
        return (_CAT_ORDER.index(cat), cat)
    except ValueError:
        return (len(_CAT_ORDER), cat)


class _Row:
    __slots__ = ("kind", "category", "check")

    def __init__(
        self,
        kind: str,
        category: str = "",
        check: Optional[Dict] = None,
    ) -> None:
        self.kind = kind        # "header" | "check"
        self.category = category
        self.check = check


class CheckPicker:
    """Panel for enabling / disabling individual checks, grouped by category."""

    def __init__(self) -> None:
        self._checks: List[Dict] = []
        self.enabled: Set[str] = set()
        self.cursor: int = 0
        self.scroll: int = 0
        # Search
        self.search_active: bool = False
        self.search_query: str = ""
        # Collapsed categories
        self._collapsed: Set[str] = set()
        # Flat display rows rebuilt on every filter/collapse change
        self._rows: List[_Row] = []

    # ── Data ──────────────────────────────────────────────────────────────────

    def load_checks(self, checks: List[Dict]) -> None:
        self._checks = checks
        self.enabled = {c["name"] for c in checks}
        self._collapsed = set()
        self.search_query = ""
        self.search_active = False
        self.cursor = 0
        self.scroll = 0
        self._rebuild_rows()

    @property
    def enabled_checks(self) -> Set[str]:
        return self.enabled

    # ── Internal ──────────────────────────────────────────────────────────────

    def _visible_checks(self) -> List[Dict]:
        if not self.search_query:
            return self._checks
        q = self.search_query.lower()
        return [
            c for c in self._checks
            if q in c["name"].lower()
            or q in c.get("description", "").lower()
            or q in c.get("category", "").lower()
        ]

    def _rebuild_rows(self) -> None:
        rows: List[_Row] = []
        visible = self._visible_checks()

        by_cat: Dict[str, List[Dict]] = defaultdict(list)
        for chk in visible:
            by_cat[chk.get("category", "DRC")].append(chk)

        for cat in sorted(by_cat.keys(), key=_cat_sort_key):
            rows.append(_Row(kind="header", category=cat))
            if cat not in self._collapsed:
                for chk in by_cat[cat]:
                    rows.append(_Row(kind="check", category=cat, check=chk))

        self._rows = rows

    def _current_check(self) -> Optional[Dict]:
        if 0 <= self.cursor < len(self._rows):
            row = self._rows[self.cursor]
            if row.kind == "check":
                return row.check
        return None

    # ── Key handling ──────────────────────────────────────────────────────────

    def handle_key(self, key: int) -> Optional[str]:
        # ── Search mode ───────────────────────────────────────────────────────
        if self.search_active:
            if key == 27:                                        # ESC — cancel
                self.search_active = False
                self.search_query = ""
                self.cursor = 0
                self.scroll = 0
                self._rebuild_rows()
                return None
            if key in (ord("\r"), ord("\n"), curses.KEY_ENTER):  # Enter — confirm
                self.search_active = False
                return None
            if key in (curses.KEY_BACKSPACE, ord("\x7f"), 263):
                self.search_query = self.search_query[:-1]
                self.cursor = 0
                self.scroll = 0
                self._rebuild_rows()
                return None
            if key == curses.KEY_UP:
                if self.cursor > 0:
                    self.cursor -= 1
                return None
            if key == curses.KEY_DOWN:
                if self.cursor < len(self._rows) - 1:
                    self.cursor += 1
                return None
            if 32 <= key <= 126:
                self.search_query += chr(key)
                self.cursor = 0
                self.scroll = 0
                self._rebuild_rows()
                return None
            return None

        # ── Normal mode ───────────────────────────────────────────────────────
        if not self._checks:
            if key == ord("/"):
                self.search_active = True
                self._rebuild_rows()
            return None

        if key == ord("/"):
            self.search_active = True
            return None

        if key == 27:  # ESC — clear search filter
            if self.search_query:
                self.search_query = ""
                self.cursor = 0
                self.scroll = 0
                self._rebuild_rows()
            return None

        if key == curses.KEY_UP:
            if self.cursor > 0:
                self.cursor -= 1
        elif key == curses.KEY_DOWN:
            if self.cursor < len(self._rows) - 1:
                self.cursor += 1
        elif key == curses.KEY_PPAGE:
            self.cursor = max(0, self.cursor - 10)
        elif key == curses.KEY_NPAGE:
            self.cursor = min(len(self._rows) - 1, self.cursor + 10)
        elif key == ord(" "):
            row = self._rows[self.cursor] if self._rows else None
            if row is None:
                pass
            elif row.kind == "header":
                # Space on header collapses/expands the category
                cat = row.category
                if cat in self._collapsed:
                    self._collapsed.discard(cat)
                else:
                    self._collapsed.add(cat)
                self._rebuild_rows()
                self.cursor = min(self.cursor, max(0, len(self._rows) - 1))
            elif row.kind == "check" and row.check is not None:
                name = row.check["name"]
                if name in self.enabled:
                    self.enabled.discard(name)
                else:
                    self.enabled.add(name)
        elif key in (ord("\r"), ord("\n"), curses.KEY_ENTER):
            # Enter on a header also collapses/expands
            row = self._rows[self.cursor] if self._rows else None
            if row and row.kind == "header":
                cat = row.category
                if cat in self._collapsed:
                    self._collapsed.discard(cat)
                else:
                    self._collapsed.add(cat)
                self._rebuild_rows()
                self.cursor = min(self.cursor, max(0, len(self._rows) - 1))
        elif key in (ord("a"), ord("A")):
            # Enable all visible checks
            for chk in self._visible_checks():
                self.enabled.add(chk["name"])
        elif key in (ord("n"), ord("N")):
            # Disable all visible checks
            for chk in self._visible_checks():
                self.enabled.discard(chk["name"])

        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, win: "curses.window") -> None:
        win.erase()
        h, w = win.getmaxyx()
        if h < 2 or w < 10:
            return

        has_bar = self.search_active or bool(self.search_query)
        content_h = h - (1 if has_bar else 0)

        # Row 0: summary
        n_on = len(self.enabled)
        n_tot = len(self._checks)
        filt_note = f"  filter:\"{self.search_query}\"" if self.search_query else ""
        summary = f" {n_on}/{n_tot} enabled{filt_note}"
        try:
            win.attron(curses.color_pair(_CP_ACCENT))
            win.addnstr(0, 0, summary, w - 1)
            win.attroff(curses.color_pair(_CP_ACCENT))
        except curses.error:
            pass

        list_h = content_h - 1
        if list_h < 1 or not self._rows:
            if has_bar:
                self._draw_search_bar(win, h - 1, w)
            return

        # Scroll
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + list_h:
            self.scroll = self.cursor - list_h + 1

        for row_idx in range(list_h):
            idx = self.scroll + row_idx
            screen_row = row_idx + 1
            if idx >= len(self._rows):
                break

            row = self._rows[idx]
            is_cur = idx == self.cursor

            try:
                if row.kind == "header":
                    cat = row.category
                    # Count enabled in this category (total checks, not filtered)
                    cat_all = [c for c in self._checks if c.get("category", "DRC") == cat]
                    cat_on = sum(1 for c in cat_all if c["name"] in self.enabled)
                    caret = "\u25bc" if cat not in self._collapsed else "\u25b6"
                    text = f"{caret} {cat}  ({cat_on}/{len(cat_all)})"
                    attr = curses.color_pair(_CP_SECTION) | curses.A_BOLD
                    if is_cur:
                        attr |= curses.A_REVERSE
                    win.attron(attr)
                    win.addnstr(screen_row, 0, text.ljust(w - 1), w - 1)
                    win.attroff(attr)

                elif row.kind == "check" and row.check is not None:
                    chk = row.check
                    name = chk["name"]
                    cat = chk.get("category", "DRC")
                    desc = chk.get("description", "")
                    is_on = name in self.enabled

                    status = "[\u2713]" if is_on else "[ ]"

                    if w >= 56:
                        cat_w = 5
                        name_w = min(26, max(8, w - cat_w - 16))
                        desc_w = max(4, w - cat_w - name_w - 14)
                        line = (
                            f"  {status} {cat[:cat_w]:<{cat_w}}  "
                            f"{name[:name_w]:<{name_w}}  {desc[:desc_w]}"
                        )
                    elif w >= 32:
                        name_w = max(6, w - 10)
                        line = f"  {status}  {name[:name_w]}"
                    else:
                        line = f" {status} {name[:w - 6]}"

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

        if has_bar:
            self._draw_search_bar(win, h - 1, w)

    def _draw_search_bar(self, win: "curses.window", row: int, w: int) -> None:
        try:
            if self.search_active:
                if not self.search_query:
                    hint = "  Search by name, description, or category  [Esc] cancel"
                    win.attron(curses.A_DIM)
                    win.addnstr(row, 0, hint, w - 1)
                    win.attroff(curses.A_DIM)
                    win.attron(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                    win.addnstr(row, 0, " /", 2)
                    win.attroff(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                else:
                    bar = f" /{self.search_query}\u258e"
                    win.attron(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                    win.addnstr(row, 0, bar.ljust(w), w - 1)
                    win.attroff(curses.color_pair(_CP_SEL) | curses.A_BOLD)
            elif self.search_query:
                n = len(self._visible_checks())
                bar = (
                    f" filter:\"{self.search_query}\""
                    f"  {n}/{len(self._checks)} shown"
                    f"  [/] edit  [Esc] clear"
                )
                win.attron(curses.color_pair(_CP_INFO))
                win.addnstr(row, 0, bar, w - 1)
                win.attroff(curses.color_pair(_CP_INFO))
        except curses.error:
            pass
