"""Plain-text log writer.

Produces: <input_stem>_review_<timestamp>.log
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from schem_review.model import Finding


def write_log(source_path: str, findings: List[Finding]) -> Path:
    """Write a plain-text log file next to *source_path*.

    Returns the path of the written file.
    """
    src = Path(source_path)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = src.parent / f"{src.stem}_review_{ts}.log"

    lines: List[str] = []
    lines.append(f"schem_review log — {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Source: {source_path}")
    lines.append(f"Findings: {len(findings)}")
    lines.append("-" * 80)

    for f in findings:
        affected_str = ", ".join(f.affected) if f.affected else "—"
        sheet_str = f" [sheet: {f.sheet}]" if f.sheet else ""
        lines.append(
            f"[{f.severity.value}] {f.check_name} | {f.message} | "
            f"affected: {affected_str}{sheet_str}"
        )

    lines.append("-" * 80)
    lines.append(f"End of report ({len(findings)} findings)")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
