"""Results view panel — severity-grouped findings with collapsible sections."""
from __future__ import annotations

import curses
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from schem_review.model import Finding, Severity

# Display order for severities
_SEV_ORDER = [Severity.ERROR, Severity.WARN, Severity.INFO]

_SEV_LABELS = {
    Severity.ERROR: "ERROR",
    Severity.WARN: "WARN ",
    Severity.INFO: "INFO ",
}

# Color pair IDs (must match app.py initialization)
_SEV_PAIRS = {
    Severity.ERROR: 5,
    Severity.WARN:  6,
    Severity.INFO:  7,
}

PAIR_SELECTED = 3
PAIR_SECTION  = 12


class _Row:
    """A displayable row in the results list."""
    __slots__ = ("kind", "severity", "finding", "expanded", "indent")

    def __init__(
        self,
        kind: str,  # "section_header" | "finding" | "detail"
        severity: Optional[Severity] = None,
        finding: Optional[Finding] = None,
        expanded: bool = False,
        indent: int = 0,
    ) -> None:
        self.kind = kind
        self.severity = severity
        self.finding = finding
        self.expanded = expanded
        self.indent = indent


class ResultsView:
    """Panel showing check findings grouped by severity."""

    def __init__(self) -> None:
        self._findings: List[Finding] = []
        self._rows: List[_Row] = []
        self._collapsed: Set[Severity] = set()
        self.cursor: int = 0
        self.scroll: int = 0
        self._expanded_findings: Set[int] = set()  # indices into _findings list

    # ------------------------------------------------------------------

    def set_findings(self, findings: List[Finding]) -> None:
        self._findings = findings
        self._collapsed = set()
        self._expanded_findings = set()
        self.cursor = 0
        self.scroll = 0
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        rows: List[_Row] = []

        by_sev: Dict[Severity, List[Finding]] = defaultdict(list)
        for f in self._findings:
            by_sev[f.severity].append(f)

        for sev in _SEV_ORDER:
            sev_findings = by_sev.get(sev, [])
            if not sev_findings:
                continue
            header = _Row(kind="section_header", severity=sev)
            rows.append(header)
            if sev in self._collapsed:
                continue
            for f in sev_findings:
                f_idx = self._findings.index(f)
                row = _Row(kind="finding", severity=sev, finding=f, indent=2)
                rows.append(row)
                if f_idx in self._expanded_findings:
                    # Affected line
                    if f.affected:
                        rows.append(_Row(kind="detail", severity=sev, finding=f, indent=4))

        self._rows = rows

    # ------------------------------------------------------------------

    def handle_key(self, key: int) -> Optional[str]:
        if not self._rows:
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
                # Adjust cursor after rebuild
                self.cursor = min(self.cursor, max(0, len(self._rows) - 1))
            elif row.kind == "finding" and row.finding is not None:
                f_idx = self._findings.index(row.finding)
                if f_idx in self._expanded_findings:
                    self._expanded_findings.discard(f_idx)
                else:
                    self._expanded_findings.add(f_idx)
                self._rebuild_rows()
        elif key == curses.KEY_PPAGE:
            self.cursor = max(0, self.cursor - 10)
        elif key == curses.KEY_NPAGE:
            self.cursor = min(len(self._rows) - 1, self.cursor + 10)
        return None

    # ------------------------------------------------------------------

    def draw(self, win: "curses.window") -> None:
        win.erase()
        h, w = win.getmaxyx()
        if h < 3 or w < 20:
            return

        if not self._findings:
            try:
                msg = "No findings — run a check first ([R] from any tab)"
                win.addnstr(h // 2, max(0, (w - len(msg)) // 2), msg, w - 1)
            except curses.error:
                pass
            return

        # Summary bar (row 0)
        by_sev: Dict[Severity, int] = defaultdict(int)
        for f in self._findings:
            by_sev[f.severity] += 1
        summary = (
            f" Total: {len(self._findings)}"
            f"  ERR:{by_sev[Severity.ERROR]}"
            f"  WRN:{by_sev[Severity.WARN]}"
            f"  INF:{by_sev[Severity.INFO]}"
            f"  (↵ to expand/collapse)"
        )
        try:
            win.attron(curses.A_BOLD)
            win.addnstr(0, 0, summary, w - 1)
            win.attroff(curses.A_BOLD)
        except curses.error:
            pass

        list_h = h - 2
        if list_h < 1 or not self._rows:
            return

        # Adjust scroll
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
                    count = sum(1 for f in self._findings if f.severity == sev)
                    caret = "▼" if sev not in self._collapsed else "▶"
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
                    is_exp = f_idx in self._expanded_findings
                    caret = "▼" if is_exp else "▶"
                    check_abbr = f.check_name[:20]
                    msg_w = max(w - row.indent - 25, 10)
                    text = f"{indent}{caret} [{check_abbr:<20}] {f.message[:msg_w]}"
                    if is_sel:
                        win.attron(curses.color_pair(PAIR_SELECTED) | curses.A_BOLD)
                        win.addnstr(screen_row, 0, text, w - 1)
                        win.attroff(curses.color_pair(PAIR_SELECTED) | curses.A_BOLD)
                    else:
                        win.addnstr(screen_row, 0, text, w - 1)

                elif row.kind == "detail" and row.finding is not None:
                    f = row.finding
                    affected = ", ".join(f.affected) if f.affected else "—"
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

        # Footer
        hint = " ↑↓ navigate  ↵ expand/collapse  PgUp/PgDn scroll"
        try:
            win.attron(curses.A_DIM)
            win.addnstr(h - 1, 0, hint, w - 1)
            win.attroff(curses.A_DIM)
        except curses.error:
            pass
