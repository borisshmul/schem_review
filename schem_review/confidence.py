"""Confidence-based severity filter.

Applied after checks run, before findings reach the report or UI.

Rules (per the principal-architect spec):
    ≥ 0.90  — emit at full severity (no change)
    0.75–0.89 — downgrade one level (CRITICAL→ERROR, ERROR→WARN, etc.)
    0.60–0.74 — downgrade two levels, append "[heuristic]" to message
    < 0.60  — suppress unless verbose=True (emitted as INFO with "[low-confidence]")
"""
from __future__ import annotations

from dataclasses import replace
from typing import List

from schem_review.model import Finding, Severity

_SEV_ORDER = [Severity.CRITICAL, Severity.ERROR, Severity.WARN, Severity.INFO]


def _downgrade(sev: Severity, levels: int) -> Severity:
    idx = _SEV_ORDER.index(sev)
    return _SEV_ORDER[min(idx + levels, len(_SEV_ORDER) - 1)]


def apply_confidence_filter(
    findings: List[Finding],
    verbose: bool = False,
) -> List[Finding]:
    """Downgrade or suppress findings whose confidence score is below threshold.

    Returns a new list; the originals are never mutated.
    """
    result: List[Finding] = []
    for f in findings:
        c = f.confidence
        if c >= 0.90:
            result.append(f)
        elif c >= 0.75:
            result.append(replace(f, severity=_downgrade(f.severity, 1)))
        elif c >= 0.60:
            msg = f.message
            if "[heuristic]" not in msg:
                msg = msg + "  [heuristic]"
            result.append(replace(f, severity=_downgrade(f.severity, 2), message=msg))
        else:
            # Below 0.60: suppress in normal mode, emit as INFO in verbose mode
            if verbose:
                msg = f.message
                if "[low-confidence]" not in msg:
                    msg = msg + "  [low-confidence]"
                result.append(replace(f, severity=Severity.INFO, message=msg))
    return result
