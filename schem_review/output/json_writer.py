"""JSON report writer.

Produces: <input_stem>_review_<timestamp>.json

Schema::

    {
      "source": "<path>",
      "generated": "<ISO timestamp>",
      "summary": {
        "total": N, "CRITICAL": N, "ERROR": N, "WARN": N, "INFO": N,
        "waived": N
      },
      "findings": [
        {
          "id": "...",
          "check": "...",
          "severity": "CRITICAL|ERROR|WARN|INFO",
          "message": "...",
          "affected": [...],
          "sheet": "...",
          "confidence": 0.95
        },
        ...
      ],
      "waived": [
        {
          "finding": { <same schema as above> },
          "waiver": { "check": "...", "net": "...", "reason": "...", "author": "..." }
        },
        ...
      ]
    }
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from schem_review.model import Finding, Severity


def write_json(
    source_path: str,
    findings: List[Finding],
    waived: Optional[List[Dict]] = None,
) -> Path:
    """Write a machine-readable JSON report next to *source_path*.

    *waived* is an optional list of ``{"finding": Finding, "waiver": dict}`` dicts
    produced by :func:`schem_review.waivers.apply_waivers`.

    Returns the path of the written file.
    """
    src = Path(source_path)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = src.parent / f"{src.stem}_review_{ts}.json"
    waived = waived or []

    summary: Dict[str, int] = {
        "total":    len(findings),
        "CRITICAL": 0,
        "ERROR":    0,
        "WARN":     0,
        "INFO":     0,
        "waived":   len(waived),
    }
    for f in findings:
        summary[f.severity.value] += 1

    def _finding_dict(f: Finding) -> Dict:
        return {
            "id":         f.id,
            "check":      f.check_name,
            "severity":   f.severity.value,
            "message":    f.message,
            "affected":   f.affected,
            "sheet":      f.sheet,
            "confidence": round(f.confidence, 3),
        }

    payload = {
        "source":    source_path,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "summary":   summary,
        "findings":  [_finding_dict(f) for f in findings],
        "waived": [
            {
                "finding": _finding_dict(entry["finding"]),
                "waiver":  entry["waiver"],
            }
            for entry in waived
        ],
    }

    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path
