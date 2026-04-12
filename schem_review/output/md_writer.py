"""Markdown report writer.

Produces: <input_stem>_review_<timestamp>.md
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from schem_review.model import Finding, Severity


def write_md(source_path: str, findings: List[Finding]) -> Path:
    """Write a structured Markdown report next to *source_path*.

    Returns the path of the written file.
    """
    src = Path(source_path)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = src.parent / f"{src.stem}_review_{ts}.md"

    lines: List[str] = []

    # ---- Header --------------------------------------------------------
    lines.append(f"# schem_review Report")
    lines.append(f"")
    lines.append(f"**Source:** `{source_path}`  ")
    lines.append(f"**Generated:** {datetime.now().isoformat(timespec='seconds')}  ")
    lines.append(f"**Total findings:** {len(findings)}")
    lines.append("")

    # ---- Summary table -------------------------------------------------
    # Group by check name
    by_check: Dict[str, Dict[str, int]] = defaultdict(lambda: {"ERROR": 0, "WARN": 0, "INFO": 0})
    for f in findings:
        by_check[f.check_name][f.severity.value] += 1

    if by_check:
        lines.append("## Summary")
        lines.append("")
        lines.append("| Check | ERROR | WARN | INFO |")
        lines.append("|-------|------:|-----:|-----:|")
        for check_name in sorted(by_check):
            counts = by_check[check_name]
            lines.append(
                f"| `{check_name}` | {counts['ERROR']} | {counts['WARN']} | {counts['INFO']} |"
            )
        lines.append("")

    # ---- Findings by severity, then by check ---------------------------
    for severity in (Severity.ERROR, Severity.WARN, Severity.INFO):
        sev_findings = [f for f in findings if f.severity == severity]
        if not sev_findings:
            continue

        lines.append(f"## {severity.value} ({len(sev_findings)})")
        lines.append("")

        by_check_sev: Dict[str, List[Finding]] = defaultdict(list)
        for f in sev_findings:
            by_check_sev[f.check_name].append(f)

        for check_name in sorted(by_check_sev):
            grp = by_check_sev[check_name]
            lines.append(f"### `{check_name}` — {len(grp)} finding(s)")
            lines.append("")
            for f in grp:
                lines.append(f"- **{f.message}**")
                if f.affected:
                    lines.append(f"  - Affected: `{', '.join(f.affected)}`")
                if f.sheet:
                    lines.append(f"  - Sheet: `{f.sheet}`")
            lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
