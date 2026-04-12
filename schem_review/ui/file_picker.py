"""Interactive file browser panel with live search."""
from __future__ import annotations

import curses
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

_ALLOWED_EXT = {".xml", ".hkp", ".net", ".netlist"}

# Color pair IDs — must match app.py
_CP_SEL     = 3
_CP_DIR     = 16
_CP_FILE_OK = 17
_CP_ACCENT  = 19
_CP_INFO    = 7


class _Entry:
    __slots__ = ("is_dir", "name", "path", "size", "mtime")

    def __init__(self, is_dir: bool, name: str, path: Path, size: int, mtime: float) -> None:
        self.is_dir = is_dir
        self.name = name
        self.path = path
        self.size = size
        self.mtime = mtime


def _load_dir(directory: Path) -> List[_Entry]:
    entries: List[_Entry] = []
    try:
        for item in sorted(
            directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
        ):
            try:
                stat = item.stat()
                entries.append(
                    _Entry(
                        is_dir=item.is_dir(),
                        name=item.name,
                        path=item,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                    )
                )
            except OSError:
                pass
    except PermissionError:
        pass
    return entries


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size // 1024}K"
    return f"{size // (1024 * 1024)}M"


def _fmt_mtime(mtime: float) -> str:
    return datetime.fromtimestamp(mtime).strftime("%y-%m-%d %H:%M")


class FilePicker:
    """Directory-browsing panel for selecting a schematic file."""

    def __init__(self, start_dir: Optional[str] = None) -> None:
        self.current_dir = Path(start_dir or os.getcwd()).resolve()
        self.entries: List[_Entry] = []
        self.cursor: int = 0
        self.scroll: int = 0
        self.selected_file: Optional[str] = None
        # Search state
        self.search_active: bool = False
        self.search_query: str = ""
        self._refresh_entries()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _refresh_entries(self) -> None:
        self.entries = _load_dir(self.current_dir)
        self.cursor = 0
        self.scroll = 0

    def _enter_dir(self, path: Path) -> None:
        self.current_dir = path.resolve()
        self.search_query = ""
        self.search_active = False
        self.cursor = 0
        self.scroll = 0
        self._refresh_entries()

    def _go_up(self) -> None:
        parent = self.current_dir.parent
        if parent != self.current_dir:
            old_name = self.current_dir.name
            self._enter_dir(parent)
            for i, e in enumerate(self.entries):
                if e.name == old_name:
                    self.cursor = i
                    break

    @property
    def _visible(self) -> List[_Entry]:
        """Entries filtered by the current search query."""
        if not self.search_query:
            return self.entries
        q = self.search_query.lower()
        return [e for e in self.entries if q in e.name.lower()]

    # ── Key handling ──────────────────────────────────────────────────────────

    def handle_key(self, key: int) -> Optional[str]:
        """Process a key. Returns 'file_selected' when a file is chosen."""

        # ── Search mode ──────────────────────────────────────────────────────
        if self.search_active:
            if key == 27:                                   # ESC — clear + exit
                self.search_active = False
                self.search_query = ""
                self.cursor = 0
                self.scroll = 0
                return None
            if key in (ord("\r"), ord("\n"), curses.KEY_ENTER):  # Enter — keep filter
                self.search_active = False
                return None
            if key in (curses.KEY_BACKSPACE, ord("\x7f"), 263):
                self.search_query = self.search_query[:-1]
                self.cursor = 0
                self.scroll = 0
                return None
            if key == curses.KEY_UP:
                if self.cursor > 0:
                    self.cursor -= 1
                return None
            if key == curses.KEY_DOWN:
                vis = self._visible
                if self.cursor < len(vis) - 1:
                    self.cursor += 1
                return None
            if key in (curses.KEY_RIGHT, curses.KEY_ENTER):
                vis = self._visible
                if vis and self.cursor < len(vis):
                    entry = vis[self.cursor]
                    if entry.is_dir:
                        self._enter_dir(entry.path)
                    elif entry.path.suffix.lower() in _ALLOWED_EXT:
                        self.selected_file = str(entry.path)
                        self.search_active = False
                        return "file_selected"
                return None
            if 32 <= key <= 126:                           # printable → append
                self.search_query += chr(key)
                self.cursor = 0
                self.scroll = 0
                return None
            return None

        # ── Normal mode ───────────────────────────────────────────────────────
        vis = self._visible

        if key == ord("/"):
            self.search_active = True
            self.cursor = 0
            self.scroll = 0
            return None

        if not vis:
            if key in (curses.KEY_LEFT, curses.KEY_BACKSPACE, ord("\x7f")):
                self._go_up()
            return None

        if key == curses.KEY_UP:
            if self.cursor > 0:
                self.cursor -= 1
        elif key == curses.KEY_DOWN:
            if self.cursor < len(vis) - 1:
                self.cursor += 1
        elif key in (curses.KEY_LEFT, curses.KEY_BACKSPACE, ord("\x7f"), 27):
            if self.search_query:
                self.search_query = ""
                self.cursor = 0
            else:
                self._go_up()
        elif key in (curses.KEY_RIGHT, ord("\r"), ord("\n"), curses.KEY_ENTER):
            entry = vis[self.cursor]
            if entry.is_dir:
                self._enter_dir(entry.path)
            elif entry.path.suffix.lower() in _ALLOWED_EXT:
                self.selected_file = str(entry.path)
                return "file_selected"
        elif key == curses.KEY_PPAGE:
            self.cursor = max(0, self.cursor - 10)
        elif key == curses.KEY_NPAGE:
            self.cursor = min(len(vis) - 1, self.cursor + 10)

        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, win: "curses.window") -> None:
        win.erase()
        h, w = win.getmaxyx()
        if h < 2 or w < 6:
            return

        # Reserve bottom row for search bar if active or filter is set
        has_bar = self.search_active or bool(self.search_query)
        list_rows = h - 1 - (1 if has_bar else 0)

        # Row 0: current directory path
        dir_str = str(self.current_dir)
        if len(dir_str) > w - 3:
            dir_str = "\u2026" + dir_str[-(w - 4):]
        try:
            win.attron(curses.color_pair(_CP_ACCENT))
            win.addnstr(0, 0, f" {dir_str}", w - 1)
            win.attroff(curses.color_pair(_CP_ACCENT))
        except curses.error:
            pass

        vis = self._visible
        list_h = list_rows - 1   # subtract path row
        if list_h < 1:
            return

        # Scroll
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + list_h:
            self.scroll = self.cursor - list_h + 1

        show_meta = w >= 38

        for row_idx in range(list_h):
            entry_idx = self.scroll + row_idx
            screen_row = row_idx + 1
            if entry_idx >= len(vis):
                break

            entry = vis[entry_idx]
            is_cur = entry_idx == self.cursor
            is_sel = self.selected_file == str(entry.path) and not entry.is_dir

            if entry.is_dir:
                icon = "\u25b6 "
                name_str = f"{icon}{entry.name}/"
            elif entry.path.suffix.lower() in _ALLOWED_EXT:
                icon = "\u25c6 " if is_sel else "\u00b7 "
                name_str = f"{icon}{entry.name}"
            else:
                icon = "  "
                name_str = f"{icon}{entry.name}"

            if show_meta:
                name_col_w = max(8, w - 21)
                name_str = name_str[:name_col_w]
                size_str = _fmt_size(entry.size) if not entry.is_dir else "     "
                mtime_str = _fmt_mtime(entry.mtime)
                line = f"{name_str:<{name_col_w}} {size_str:>5} {mtime_str}"
            else:
                line = name_str[: w - 2]

            if is_sel and len(line) < w - 3:
                line = line.rstrip() + " \u25c0"

            try:
                if is_cur:
                    win.attron(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                elif entry.is_dir:
                    win.attron(curses.color_pair(_CP_DIR) | curses.A_BOLD)
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(curses.color_pair(_CP_DIR) | curses.A_BOLD)
                elif entry.path.suffix.lower() in _ALLOWED_EXT:
                    attr = curses.color_pair(_CP_FILE_OK)
                    if is_sel:
                        attr |= curses.A_BOLD
                    win.attron(attr)
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(attr)
                else:
                    win.attron(curses.A_DIM)
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(curses.A_DIM)
            except curses.error:
                pass

        # Search bar at bottom
        bar_row = h - 1
        try:
            if self.search_active:
                bar = f" /{self.search_query}\u258e"    # blinking cursor look
                win.attron(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                win.addnstr(bar_row, 0, bar.ljust(w), w - 1)
                win.attroff(curses.color_pair(_CP_SEL) | curses.A_BOLD)
            elif self.search_query:
                n = len(vis)
                bar = f" filter:\"{self.search_query}\"  {n} match{'es' if n != 1 else ''}  [/] edit  [Esc] clear"
                win.attron(curses.color_pair(_CP_INFO))
                win.addnstr(bar_row, 0, bar, w - 1)
                win.attroff(curses.color_pair(_CP_INFO))
        except curses.error:
            pass
