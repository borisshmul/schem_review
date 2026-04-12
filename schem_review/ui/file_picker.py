"""Interactive file browser panel."""
from __future__ import annotations

import curses
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# Allowed file extensions for selection
_ALLOWED_EXT = {".xml", ".hkp", ".net", ".netlist"}


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
        for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                stat = item.stat()
                entries.append(_Entry(
                    is_dir=item.is_dir(),
                    name=item.name,
                    path=item,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                ))
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
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


class FilePicker:
    """Directory-browsing panel for selecting a schematic file."""

    PAIR_NORMAL = 1
    PAIR_SELECTED = 3
    PAIR_DIM = 9

    def __init__(self, start_dir: Optional[str] = None) -> None:
        self.current_dir = Path(start_dir or os.getcwd()).resolve()
        self.entries: List[_Entry] = []
        self.cursor: int = 0
        self.scroll: int = 0
        self.selected_file: Optional[str] = None
        self._refresh_entries()

    # ------------------------------------------------------------------

    def _refresh_entries(self) -> None:
        self.entries = _load_dir(self.current_dir)
        self.cursor = min(self.cursor, max(0, len(self.entries) - 1))
        self.scroll = 0

    def _enter_dir(self, path: Path) -> None:
        self.current_dir = path.resolve()
        self.cursor = 0
        self.scroll = 0
        self._refresh_entries()

    def _go_up(self) -> None:
        parent = self.current_dir.parent
        if parent != self.current_dir:
            old_name = self.current_dir.name
            self._enter_dir(parent)
            # Try to position cursor on the directory we came from
            for i, e in enumerate(self.entries):
                if e.name == old_name:
                    self.cursor = i
                    break

    # ------------------------------------------------------------------

    def handle_key(self, key: int) -> Optional[str]:
        """Process a key event. Returns 'file_selected' or None."""
        if not self.entries:
            if key == curses.KEY_LEFT or key == curses.KEY_BACKSPACE or key == ord("\x7f"):
                self._go_up()
            return None

        if key == curses.KEY_UP:
            if self.cursor > 0:
                self.cursor -= 1
        elif key == curses.KEY_DOWN:
            if self.cursor < len(self.entries) - 1:
                self.cursor += 1
        elif key in (curses.KEY_LEFT, curses.KEY_BACKSPACE, ord("\x7f"), 27):
            self._go_up()
        elif key in (curses.KEY_RIGHT, ord("\r"), ord("\n"), curses.KEY_ENTER):
            entry = self.entries[self.cursor]
            if entry.is_dir:
                self._enter_dir(entry.path)
            elif entry.path.suffix.lower() in _ALLOWED_EXT:
                self.selected_file = str(entry.path)
                return "file_selected"
        elif key == curses.KEY_PPAGE:  # page up
            self.cursor = max(0, self.cursor - 10)
        elif key == curses.KEY_NPAGE:  # page down
            self.cursor = min(len(self.entries) - 1, self.cursor + 10)
        return None

    # ------------------------------------------------------------------

    def draw(self, win: "curses.window") -> None:
        win.erase()
        h, w = win.getmaxyx()
        if h < 3 or w < 10:
            return

        # Header: current directory
        dir_str = f" {self.current_dir} "
        try:
            win.attron(curses.color_pair(self.PAIR_SELECTED) | curses.A_BOLD)
            win.addnstr(0, 0, dir_str.ljust(w), w - 1)
            win.attroff(curses.color_pair(self.PAIR_SELECTED) | curses.A_BOLD)
        except curses.error:
            pass

        # Column headers
        col_hdr = f"  {'Name':<{w-30}}  {'Size':>8}  {'Modified':<17}"
        try:
            win.attron(curses.A_UNDERLINE)
            win.addnstr(1, 0, col_hdr, w - 1)
            win.attroff(curses.A_UNDERLINE)
        except curses.error:
            pass

        list_h = h - 2  # rows available for listing
        if list_h < 1:
            return

        # Adjust scroll
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + list_h:
            self.scroll = self.cursor - list_h + 1

        for row_idx in range(list_h):
            entry_idx = self.scroll + row_idx
            screen_row = row_idx + 2
            if entry_idx >= len(self.entries):
                break

            entry = self.entries[entry_idx]
            is_sel = entry_idx == self.cursor

            if entry.is_dir:
                icon = "▶ "
                name_display = f"{icon}{entry.name}/"
                attr = curses.A_BOLD
            elif entry.path.suffix.lower() in _ALLOWED_EXT:
                icon = "  "
                name_display = f"{icon}{entry.name}"
                attr = curses.A_NORMAL
            else:
                icon = "  "
                name_display = f"{icon}{entry.name}"
                attr = curses.A_DIM

            name_col_w = max(w - 30, 10)
            name_display = name_display[:name_col_w]
            size_str = _fmt_size(entry.size) if not entry.is_dir else "<DIR>"
            mtime_str = _fmt_mtime(entry.mtime)

            line = f"{name_display:<{name_col_w}}  {size_str:>8}  {mtime_str:<17}"

            try:
                if is_sel:
                    win.attron(curses.color_pair(self.PAIR_SELECTED) | curses.A_BOLD)
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(curses.color_pair(self.PAIR_SELECTED) | curses.A_BOLD)
                else:
                    win.attron(attr)
                    win.addnstr(screen_row, 0, line, w - 1)
                    win.attroff(attr)
            except curses.error:
                pass

        # Footer hint
        hint = " ↑↓ navigate  ↵/→ open  ← parent  (select .xml or .hkp)"
        try:
            win.attron(curses.A_DIM)
            win.addnstr(h - 1, 0, hint, w - 1)
            win.attroff(curses.A_DIM)
        except curses.error:
            pass
