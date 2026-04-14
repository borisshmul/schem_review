"""Markdown report writer.

Produces: <input_stem>_review_<timestamp>.md

Features:
- CRITICAL tier displayed before ERRORs with a prominent header
- Long check groups (>5 findings) are truncated with a "see JSON" note
- Low-confidence findings are flagged with an italic heuristic note
- Waived findings appear in a separate Acknowledged section
- Sheet-level summary at the end
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from schem_review.model import Finding, Severity

# Maximum findings to show inline per check before truncating
_MAX_INLINE = 5

_SEV_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.ERROR:    "🟠",
    Severity.WARN:     "🟡",
    Severity.INFO:     "🔵",
}


def write_md(
    source_path: str,
    findings: List[Finding],
    waived: Optional[List[Dict]] = None,
) -> Path:
    """Write a structured Markdown report next to *source_path*.

    *waived* is an optional list of ``{"finding": Finding, "waiver": dict}`` dicts
    produced by :func:`schem_review.waivers.apply_waivers`.
    """
    src = Path(source_path)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = src.parent / f"{src.stem}_review_{ts}.md"
    waived = waived or []

    lines: List[str] = []

    # ── Header ───────────────────────────────────────────────────────────────
    lines += [
        "# schem_review Report",
        "",
        f"**Source:** `{source_path}`  ",
        f"**Generated:** {datetime.now().isoformat(timespec='seconds')}  ",
        f"**Active findings:** {len(findings)}  ",
        f"**Waived findings:** {len(waived)}",
        "",
    ]

    # ── Severity summary table ────────────────────────────────────────────────
    counts: Dict[str, int] = {s.value: 0 for s in Severity}
    for f in findings:
        counts[f.severity.value] += 1

    lines += [
        "## Severity Summary",
        "",
        "| Severity | Count |",
        "|----------|------:|",
    ]
    for sev in (Severity.CRITICAL, Severity.ERROR, Severity.WARN, Severity.INFO):
        emoji = _SEV_EMOJI[sev]
        lines.append(f"| {emoji} {sev.value} | {counts[sev.value]} |")
    lines.append("")

    # ── Per-check summary table ───────────────────────────────────────────────
    by_check: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {s.value: 0 for s in Severity}
    )
    for f in findings:
        by_check[f.check_name][f.severity.value] += 1

    if by_check:
        lines += [
            "## Check Summary",
            "",
            "| Check | CRITICAL | ERROR | WARN | INFO |",
            "|-------|:--------:|------:|-----:|-----:|",
        ]
        for check_name in sorted(by_check):
            c = by_check[check_name]
            lines.append(
                f"| `{check_name}` "
                f"| {c['CRITICAL']} | {c['ERROR']} | {c['WARN']} | {c['INFO']} |"
            )
        lines.append("")

    # ── Findings by severity ──────────────────────────────────────────────────
    for severity in (Severity.CRITICAL, Severity.ERROR, Severity.WARN, Severity.INFO):
        sev_findings = [f for f in findings if f.severity == severity]
        if not sev_findings:
            continue

        emoji = _SEV_EMOJI[severity]
        lines += [
            f"## {emoji} {severity.value} ({len(sev_findings)})",
            "",
        ]

        if severity == Severity.CRITICAL:
            lines += [
                "> ⚠️ **These findings indicate the board will be damaged or permanently "
                "non-functional.  Address all CRITICAL findings before ordering PCBs.**",
                "",
            ]

        by_check_sev: Dict[str, List[Finding]] = defaultdict(list)
        for f in sev_findings:
            by_check_sev[f.check_name].append(f)

        for check_name in sorted(by_check_sev):
            grp = by_check_sev[check_name]
            lines += [
                f"### `{check_name}` — {len(grp)} finding(s)",
                "",
            ]

            display = grp[:_MAX_INLINE]
            remainder = len(grp) - len(display)

            for f in display:
                conf_note = (
                    f" _(heuristic — verify manually; confidence {f.confidence:.0%})_"
                    if f.confidence < 0.85 else ""
                )
                lines.append(f"- **{f.message}**{conf_note}")
                if f.affected:
                    lines.append(f"  - Affected: `{', '.join(f.affected)}`")
                if f.sheet:
                    lines.append(f"  - Sheet: `{f.sheet}`")

            if remainder > 0:
                lines.append(
                    f"\n  _…and {remainder} more `{check_name}` finding(s) — "
                    f"see the JSON report for the complete list._"
                )
            lines.append("")

    # ── Sheet-level summary ───────────────────────────────────────────────────
    sheets_seen = sorted({f.sheet for f in findings if f.sheet})
    if sheets_seen:
        lines += ["## By Sheet", ""]
        for sheet in sheets_seen:
            sf = [f for f in findings if f.sheet == sheet]
            err  = sum(1 for f in sf if f.severity == Severity.ERROR)
            crit = sum(1 for f in sf if f.severity == Severity.CRITICAL)
            wrn  = sum(1 for f in sf if f.severity == Severity.WARN)
            inf  = sum(1 for f in sf if f.severity == Severity.INFO)
            lines += [
                f"### Sheet `{sheet}` — {len(sf)} finding(s)",
                "",
                "| Severity | Count |",
                "|----------|------:|",
                f"| CRITICAL | {crit} |",
                f"| ERROR    | {err}  |",
                f"| WARN     | {wrn}  |",
                f"| INFO     | {inf}  |",
                "",
            ]
            for f in sf:
                lines.append(
                    f"- `[{f.severity.value}]` **{f.check_name}**: {f.message}"
                )
            lines.append("")

    # ── Waived findings ───────────────────────────────────────────────────────
    if waived:
        lines += [
            "## Acknowledged / Waived Findings",
            "",
            "_These findings matched a waiver entry and are excluded from the "
            "active findings count._",
            "",
            "| Finding | Reason | Author |",
            "|---------|--------|--------|",
        ]
        for entry in waived:
            f = entry["finding"]
            w = entry["waiver"]
            reason = w.get("reason", "—")
            author = w.get("author", "—")
            lines.append(
                f"| `[{f.severity.value}]` {f.check_name}: {f.message[:80]} "
                f"| {reason} | {author} |"
            )
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
