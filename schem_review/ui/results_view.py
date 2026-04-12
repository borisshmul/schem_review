"""Results view panel with severity grouping and OR/AND/wildcard search."""
from __future__ import annotations

import curses
import re
from collections import defaultdict
from typing import Dict, List, Optional, Set

from schem_review.model import Finding, Severity

_SEV_ORDER  = [Severity.ERROR, Severity.WARN, Severity.INFO]
_SEV_LABELS = {Severity.ERROR: "ERROR", Severity.WARN: "WARN ", Severity.INFO: "INFO "}
_SEV_PAIRS  = {Severity.ERROR: 5, Severity.WARN: 6, Severity.INFO: 7}

PAIR_SELECTED = 3
PAIR_SECTION  = 12

# Color pair IDs used for search bar (must match app.py)
_CP_SEL    = 3
_CP_INFO   = 7
_CP_ACCENT = 19
_CP_WARN   = 6
_CP_ERR    = 5


# ── Search helpers ────────────────────────────────────────────────────────────

def _term_to_re(term: str) -> re.Pattern:
    """Convert a single term (may contain * wildcards) to a compiled regex."""
    parts = [re.escape(p) for p in term.split("*")]
    return re.compile(".*".join(parts))


def _match_finding(query: str, finding: Finding) -> bool:
    """
    Match a finding against a query string.

    Syntax:
      |  separates OR alternatives   e.g. error|warning
      &  separates AND requirements  e.g. net&open
      *  wildcard within a term      e.g. power*flag
    """
    text = (
        f"{finding.check_name} {finding.message} {finding.severity.value}"
    ).lower()
    query = query.strip().lower()
    if not query:
        return True

    for or_part in query.split("|"):
        and_terms = [t.strip() for t in or_part.split("&") if t.strip()]
        if not and_terms:
            continue
        all_ok = True
        for term in and_terms:
            if not term:
                continue
            try:
                if "*" in term:
                    if not _term_to_re(term).search(text):
                        all_ok = False
                        break
                else:
                    if term not in text:
                        all_ok = False
                        break
            except re.error:
                if term.replace("*", "") not in text:
                    all_ok = False
                    break
        if all_ok:
            return True
    return False


# ── Display row ───────────────────────────────────────────────────────────────

class _Row:
    __slots__ = ("kind", "severity", "finding", "indent")

    def __init__(
        self,
        kind: str,
        severity: Optional[Severity] = None,
        finding: Optional[Finding] = None,
        indent: int = 0,
    ) -> None:
        self.kind = kind
        self.severity = severity
        self.finding = finding
        self.indent = indent


# ── Main panel ────────────────────────────────────────────────────────────────

class ResultsView:
    """Panel showing check findings grouped by severity with live search."""

    def __init__(self) -> None:
        self._findings: List[Finding] = []
        self._rows: List[_Row] = []
        self._collapsed: Set[Severity] = set()
        self._expanded: Set[int] = set()   # indices into _findings
        self.cursor: int = 0
        self.scroll: int = 0
        # Search state
        self.search_active: bool = False
        self.search_query: str = ""

    # ── Data ──────────────────────────────────────────────────────────────────

    def set_findings(self, findings: List[Finding]) -> None:
        self._findings = findings
        self._collapsed = set()
        self._expanded = set()
        self.search_query = ""
        self.search_active = False
        self.cursor = 0
        self.scroll = 0
        self._rebuild_rows()

    def _visible_findings(self) -> List[Finding]:
        if not self.search_query:
            return self._findings
        return [f for f in self._findings if _match_finding(self.search_query, f)]

    def _rebuild_rows(self) -> None:
        rows: List[_Row] = []
        visible = self._visible_findings()

        by_sev: Dict[Severity, List[Finding]] = defaultdict(list)
        for f in visible:
            by_sev[f.severity].append(f)

        for sev in _SEV_ORDER:
            sev_findings = by_sev.get(sev, [])
            if not sev_findings:
                continue
            rows.append(_Row(kind="section_header", severity=sev))
            if sev in self._collapsed:
                continue
            for f in sev_findings:
                f_idx = self._findings.index(f)
                rows.append(_Row(kind="finding", severity=sev, finding=f, indent=2))
                if f_idx in self._expanded and f.affected:
                    rows.append(_Row(kind="detail", severity=sev, finding=f, indent=4))

        self._rows = rows

    # ── Key handling ──────────────────────────────────────────────────────────

    def handle_key(self, key: int) -> Optional[str]:
        # Search input mode
        if self.search_active:
            if key == 27:                                        # ESC — clear
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

        # Normal mode
        if not self._rows:
            if key == ord("/"):
                self.search_active = True
            return None

        if key == ord("/"):
            self.search_active = True
            return None

        if key == 27:   # ESC clears active filter
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
        elif key in (ord("\r"), ord("\n"), curses.KEY_ENTER):
            row = self._rows[self.cursor]
            if row.kind == "section_header":
                sev = row.severity
                if sev in self._collapsed:
                    self._collapsed.discard(sev)
                else:
                    self._collapsed.add(sev)
                self._rebuild_rows()
                self.cursor = min(self.cursor, max(0, len(self._rows) - 1))
            elif row.kind == "finding" and row.finding is not None:
                f_idx = self._findings.index(row.finding)
                if f_idx in self._expanded:
                    self._expanded.discard(f_idx)
                else:
                    self._expanded.add(f_idx)
                self._rebuild_rows()
        elif key == curses.KEY_PPAGE:
            self.cursor = max(0, self.cursor - 10)
        elif key == curses.KEY_NPAGE:
            self.cursor = min(max(0, len(self._rows) - 1), self.cursor + 10)

        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, win: "curses.window") -> None:
        win.erase()
        h, w = win.getmaxyx()
        if h < 3 or w < 20:
            return

        # Bottom row reserved for search bar if active or filter set
        has_bar = self.search_active or bool(self.search_query)
        content_h = h - (1 if has_bar else 0)

        if not self._findings:
            try:
                msg = "No findings \u2014 run checks first  ([R] from any tab)"
                win.addnstr(h // 2, max(0, (w - len(msg)) // 2), msg, w - 1)
                if has_bar:
                    self._draw_search_bar(win, h - 1, w)
            except curses.error:
                pass
            return

        # Row 0: summary
        visible = self._visible_findings()
        by_sev: Dict[Severity, int] = defaultdict(int)
        for f in visible:
            by_sev[f.severity] += 1

        filt_note = f"  (filter: \"{self.search_query}\" — {len(visible)}/{len(self._findings)})" \
            if self.search_query else ""
        summary = (
            f" Total: {len(visible)}"
            f"  \u2718ERR:{by_sev[Severity.ERROR]}"
            f"  \u26a0WRN:{by_sev[Severity.WARN]}"
            f"  \u2139INF:{by_sev[Severity.INFO]}"
            f"  (\u21b5 expand/collapse){filt_note}"
        )
        try:
            win.attron(curses.A_BOLD)
            win.addnstr(0, 0, summary, w - 1)
            win.attroff(curses.A_BOLD)
        except curses.error:
            pass

        list_h = content_h - 2
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
            is_sel = idx == self.cursor
            indent = " " * row.indent

            try:
                if row.kind == "section_header":
                    sev = row.severity
                    count = sum(1 for f in visible if f.severity == sev)
                    caret = "\u25bc" if sev not in self._collapsed else "\u25b6"
                    text = f"{caret} {_SEV_LABELS[sev]} ({count})"
                    pair = _SEV_PAIRS.get(sev, 1)
                    attr = curses.color_pair(pair) | curses.A_BOLD
                    if is_sel:
                        attr |= curses.A_REVERSE
                    win.attron(attr)
                    win.addnstr(screen_row, 0, text.ljust(w - 1), w - 1)
                    win.attroff(attr)

                elif row.kind == "finding" and row.finding is not None:
                    f = row.finding
                    f_idx = self._findings.index(f)
                    caret = "\u25bc" if f_idx in self._expanded else "\u25b6"
                    abbr = f.check_name[:20]
                    msg_w = max(w - row.indent - 26, 10)
                    text = f"{indent}{caret} [{abbr:<20}] {f.message[:msg_w]}"
                    if is_sel:
                        win.attron(curses.color_pair(PAIR_SELECTED) | curses.A_BOLD)
                        win.addnstr(screen_row, 0, text, w - 1)
                        win.attroff(curses.color_pair(PAIR_SELECTED) | curses.A_BOLD)
                    else:
                        win.addnstr(screen_row, 0, text, w - 1)

                elif row.kind == "detail" and row.finding is not None:
                    f = row.finding
                    affected = ", ".join(f.affected) if f.affected else "\u2014"
                    sheet = f"  sheet: {f.sheet}" if f.sheet else ""
                    text = f"{indent}Affected: {affected}{sheet}"
                    if is_sel:
                        win.attron(curses.color_pair(PAIR_SELECTED))
                        win.addnstr(screen_row, 0, text, w - 1)
                        win.attroff(curses.color_pair(PAIR_SELECTED))
                    else:
                        win.attron(curses.A_DIM)
                        win.addnstr(screen_row, 0, text, w - 1)
                        win.attroff(curses.A_DIM)

            except curses.error:
                pass

        # Hint row (above search bar)
        hint_row = content_h - 1
        hint = " \u2191\u2193 navigate  \u21b5 expand/collapse  PgUp/Dn scroll  / search"
        try:
            win.attron(curses.A_DIM)
            win.addnstr(hint_row, 0, hint, w - 1)
            win.attroff(curses.A_DIM)
        except curses.error:
            pass

        if has_bar:
            self._draw_search_bar(win, h - 1, w)

    def _draw_search_bar(self, win: "curses.window", row: int, w: int) -> None:
        try:
            if self.search_active:
                # Show syntax hint inline when bar is empty
                if not self.search_query:
                    hint = "  Syntax: term  |  or|or  &  and&and  *  wild*card  [Esc] cancel"
                    win.attron(curses.A_DIM)
                    win.addnstr(row, 0, hint, w - 1)
                    win.attroff(curses.A_DIM)
                    # Overwrite start with the prompt
                    win.attron(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                    win.addnstr(row, 0, " /", 2)
                    win.attroff(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                else:
                    bar = f" /{self.search_query}\u258e"
                    win.attron(curses.color_pair(_CP_SEL) | curses.A_BOLD)
                    win.addnstr(row, 0, bar.ljust(w), w - 1)
                    win.attroff(curses.color_pair(_CP_SEL) | curses.A_BOLD)
            elif self.search_query:
                n = len(self._visible_findings())
                bar = (
                    f" filter:\"{self.search_query}\""
                    f"  {n}/{len(self._findings)} shown"
                    f"  [/] edit  [Esc] clear"
                )
                win.attron(curses.color_pair(_CP_INFO))
                win.addnstr(row, 0, bar, w - 1)
                win.attroff(curses.color_pair(_CP_INFO))
        except curses.error:
            pass
