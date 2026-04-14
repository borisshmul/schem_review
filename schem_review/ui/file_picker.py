"""Interactive file browser panel with live recursive search."""
from __future__ import annotations

import curses
import fnmatch
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

_ALLOWED_EXT = {".xml", ".hkp", ".net", ".netlist", ".qcv", ".txt"}

# Directories to skip during recursive walk
_SKIP_DIRS = {
    ".git", ".venv", "venv", ".tox", "__pycache__",
    "node_modules", ".idea", ".vscode", "dist", "build",
}

# Cap on recursive search results (keeps the walk fast)
_SEARCH_MAX = 500

# Color pair IDs — must match app.py
_CP_SEL     = 3
_CP_DIR     = 16
_CP_FILE_OK = 17
_CP_ACCENT  = 19
_CP_INFO    = 7

# All key codes that mean "backspace / delete previous character"
_BACKSPACE_KEYS = {
    curses.KEY_BACKSPACE,   # 263 — most terminals
    ord("\x7f"),            # 127 — DEL / many terminals
    ord("\x08"),            # 8   — Ctrl+H / older terminals
    263,                    # explicit fallback if KEY_BACKSPACE differs
}


class _Entry:
    __slots__ = ("is_dir", "name", "path", "size", "mtime")

    def __init__(self, is_dir: bool, name: str, path: Path,
                 size: int, mtime: float) -> None:
        self.is_dir = is_dir
        self.name   = name
        self.path   = path
        self.size   = size
        self.mtime  = mtime


def _load_dir(directory: Path) -> List[_Entry]:
    entries: List[_Entry] = []
    try:
        for item in sorted(
            directory.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        ):
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
    return datetime.fromtimestamp(mtime).strftime("%y-%m-%d %H:%M")


class FilePicker:
    """Directory-browsing panel with recursive live search."""

    def __init__(self, start_dir: Optional[str] = None) -> None:
        self.root_dir    = Path(start_dir or os.getcwd()).resolve()
        self.current_dir = self.root_dir
        self.entries:   List[_Entry] = []
        self.cursor:    int = 0
        self.scroll:    int = 0
        self.selected_file: Optional[str] = None
        # Search state
        self.search_active: bool = False
        self.search_query:  str  = ""
        self._refresh_entries()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _refresh_entries(self) -> None:
        self.entries = _load_dir(self.current_dir)
        self.cursor  = 0
        self.scroll  = 0

    def _enter_dir(self, path: Path) -> None:
        self.current_dir = path.resolve()
        self.search_query  = ""
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

    def _recursive_search(self, query: str) -> List[_Entry]:
        """Walk root_dir recursively; return entries whose filename matches query.

        If the query contains ``*`` or ``?`` it is treated as a glob pattern
        (matched against the full filename).  Otherwise a plain case-insensitive
        substring match is used.
        """
        results: List[_Entry] = []
        q = query.lower()
        _is_glob = "*" in q or "?" in q

        def _matches(name: str) -> bool:
            n = name.lower()
            if _is_glob:
                return fnmatch.fnmatch(n, q)
            return q in n

        def _walk(directory: Path, depth: int) -> None:
            if depth > 10 or len(results) >= _SEARCH_MAX:
                return
            try:
                for item in sorted(
                    directory.iterdir(),
                    key=lambda p: (not p.is_dir(), p.name.lower()),
                ):
                    if len(results) >= _SEARCH_MAX:
                        return
                    if item.is_dir():
                        if item.name.startswith(".") or item.name in _SKIP_DIRS:
                            continue
                        _walk(item, depth + 1)
                    else:
                        if not _matches(item.name):
                            continue
                        try:
                            stat = item.stat()
                            try:
                                display_name = str(item.relative_to(self.root_dir))
                            except ValueError:
                                display_name = item.name
                            results.append(_Entry(
                                is_dir=False,
                                name=display_name,
                                path=item,
                                size=stat.st_size,
                                mtime=stat.st_mtime,
                            ))
                        except OSError:
                            pass
            except PermissionError:
                pass

        _walk(self.root_dir, 0)
        return results

    @property
    def _visible(self) -> List[_Entry]:
        """Entries to display — recursive search results when a query is set,
        plain directory listing otherwise."""
        if not self.search_query:
            return self.entries
        return self._recursive_search(self.search_query)

    # ── Key handling ──────────────────────────────────────────────────────────

    def handle_key(self, key: int) -> Optional[str]:
        """Process a key press.  Returns 'file_selected' when a file is chosen.

        When search_active is True the caller (app.py) must route *all* keys
        here — no app-level shortcuts should fire during text input.
        """

        # ── Search mode: typing into the search bar ───────────────────────────
        if self.search_active:
            # ESC — discard query and exit search
            if key == 27:
                self.search_active = False
                self.search_query  = ""
                self.cursor = 0
                self.scroll = 0
                return None

            # Enter — lock in the current filter, exit typing mode
            if key in (ord("\r"), ord("\n"), curses.KEY_ENTER):
                self.search_active = False
                self.cursor = 0
                self.scroll = 0
                return None

            # Backspace — delete last character, or exit search bar if query is empty
            if key in _BACKSPACE_KEYS:
                if self.search_query:
                    self.search_query = self.search_query[:-1]
                else:
                    self.search_active = False
                self.cursor = 0
                self.scroll = 0
                return None

            # Arrow navigation within results while typing
            if key == curses.KEY_UP:
                if self.cursor > 0:
                    self.cursor -= 1
                return None
            if key == curses.KEY_DOWN:
                vis = self._visible
                if self.cursor < len(vis) - 1:
                    self.cursor += 1
                return None

            # Enter a directory or select a file from results
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

            # Any printable character (including digits, symbols) → append to query
            if 32 <= key <= 126:
                self.search_query += chr(key)
                self.cursor = 0
                self.scroll = 0
                return None

            # Ignore everything else (function keys, mouse events, etc.)
            return None

        # ── Normal browsing mode ──────────────────────────────────────────────
        vis = self._visible

        # Start search — / is an explicit no-op trigger; any printable char also
        # activates search immediately so users don't need to press / first.
        if key == ord("/"):
            self.search_active = True
            self.cursor = 0
            self.scroll = 0
            return None

        if 32 <= key <= 126:
            self.search_active = True
            self.search_query += chr(key)
            self.cursor = 0
            self.scroll = 0
            return None

        if not vis:
            if key in (curses.KEY_LEFT, *_BACKSPACE_KEYS):
                self._go_up()
            return None

        if key == curses.KEY_UP:
            if self.cursor > 0:
                self.cursor -= 1

        elif key == curses.KEY_DOWN:
            if self.cursor < len(vis) - 1:
                self.cursor += 1

        elif key in (curses.KEY_LEFT, *_BACKSPACE_KEYS, 27):
            if self.search_query:
                self.search_query = ""
                self.cursor = 0
                self.scroll = 0
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

        has_bar  = self.search_active or bool(self.search_query)
        list_rows = h - 1 - (1 if has_bar else 0)

        # Row 0: path header — shows root + recursive indicator during search
        if self.search_query or self.search_active:
            dir_str = f"{self.root_dir}  [↓ recursive]"
        else:
            dir_str = str(self.current_dir)
        if len(dir_str) > w - 3:
            dir_str = "\u2026" + dir_str[-(w - 4):]
        try:
            win.attron(curses.color_pair(_CP_ACCENT))
            win.addnstr(0, 0, f" {dir_str}", w - 1)
            win.attroff(curses.color_pair(_CP_ACCENT))
        except curses.error:
            pass

        vis    = self._visible
        list_h = list_rows - 1   # subtract path row
        if list_h < 1:
            return

        # Keep cursor within the visible window
        if self.cursor >= len(vis):
            self.cursor = max(0, len(vis) - 1)
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + list_h:
            self.scroll = self.cursor - list_h + 1

        show_meta = w >= 38

        for row_idx in range(list_h):
            entry_idx  = self.scroll + row_idx
            screen_row = row_idx + 1
            if entry_idx >= len(vis):
                break

            entry  = vis[entry_idx]
            is_cur = entry_idx == self.cursor
            is_sel = self.selected_file == str(entry.path) and not entry.is_dir

            if entry.is_dir:
                icon     = "\u25b6 "
                name_str = f"{icon}{entry.name}/"
            elif entry.path.suffix.lower() in _ALLOWED_EXT:
                icon     = "\u25c6 " if is_sel else "\u00b7 "
                name_str = f"{icon}{entry.name}"
            else:
                icon     = "  "
                name_str = f"{icon}{entry.name}"

            if show_meta:
                name_col_w = max(8, w - 21)
                name_str   = name_str[:name_col_w]
                size_str   = _fmt_size(entry.size) if not entry.is_dir else "     "
                mtime_str  = _fmt_mtime(entry.mtime)
                line       = f"{name_str:<{name_col_w}} {size_str:>5} {mtime_str}"
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

        # Search / filter bar at bottom
        bar_row = h - 1
        try:
            if self.search_active:
                cursor_char = "\u258e"   # blinking-cursor look
                bar = f" /{self.search_query}{cursor_char}"
                win.attron(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                win.addnstr(bar_row, 0, bar.ljust(w), w - 1)
                win.attroff(curses.color_pair(_CP_SEL) | curses.A_BOLD)
            elif self.search_query:
                n   = len(vis)
                cap = f"  (capped at {_SEARCH_MAX})" if n >= _SEARCH_MAX else ""
                bar = (
                    f" search:\"{self.search_query}\"  "
                    f"{n} result{'s' if n != 1 else ''}{cap}"
                    f"  [/] edit  [Esc] clear"
                )
                win.attron(curses.color_pair(_CP_INFO))
                win.addnstr(bar_row, 0, bar, w - 1)
                win.attroff(curses.color_pair(_CP_INFO))
        except curses.error:
            pass
