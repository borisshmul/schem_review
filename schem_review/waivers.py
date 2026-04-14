"""Waiver system — suppress known-good findings so they don't pollute the report.

Waivers are loaded from a file next to the design:

  waivers.toml   (preferred)
  waivers.json   (fallback)

TOML format::

    [[waiver]]
    check  = "single_pin_nets"
    net    = "REG_EN#"
    reason = "Pulled high via board strap — not on schematic"
    author = "B.S."
    date   = "2026-04-13"

JSON format::

    {
      "waivers": [
        { "check": "single_pin_nets", "net": "REG_EN#",
          "reason": "...", "author": "B.S.", "date": "2026-04-13" }
      ]
    }

Matching rules (all specified fields must match):
  check    — exact check_name match
  net      — net name must appear in finding.affected or finding.message
  affected — refdes must appear in finding.affected
  id       — exact finding.id match
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from schem_review.model import Finding, Severity


def load_waivers(design_path: str) -> List[Dict]:
    """Return list of waiver dicts from waivers.toml or waivers.json, or [] if absent."""
    src = Path(design_path)

    toml_path = src.parent / "waivers.toml"
    if toml_path.exists():
        return _load_toml(toml_path)

    json_path = src.parent / "waivers.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            return data.get("waivers", [])
        except (json.JSONDecodeError, OSError):
            return []

    return []


def _load_toml(path: Path) -> List[Dict]:
    """Load waivers from a TOML file, using stdlib tomllib (3.11+) or a minimal fallback."""
    text = path.read_text(encoding="utf-8")

    # Try stdlib first (Python ≥ 3.11)
    if sys.version_info >= (3, 11):
        import tomllib  # type: ignore[import]
        try:
            data = tomllib.loads(text)
            return data.get("waiver", [])
        except Exception:
            pass

    # Try third-party tomli
    try:
        import tomli  # type: ignore[import]
        data = tomli.loads(text)
        return data.get("waiver", [])
    except ImportError:
        pass

    # Minimal built-in parser for our [[waiver]] format only
    return _parse_toml_minimal(text)


def _parse_toml_minimal(text: str) -> List[Dict]:
    """Parse [[waiver]] sections from TOML without any dependency."""
    waivers: List[Dict] = []
    current: Dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[[waiver]]":
            if current is not None:
                waivers.append(current)
            current = {}
            continue
        if current is not None and "=" in line and not line.startswith("["):
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Strip quotes
            if (val.startswith('"') and val.endswith('"')) or \
               (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            current[key] = val
    if current is not None:
        waivers.append(current)
    return waivers


# ---------------------------------------------------------------------------
# Applying waivers
# ---------------------------------------------------------------------------

def apply_waivers(
    findings: List[Finding],
    waivers: List[Dict],
) -> Tuple[List[Finding], List[Dict]]:
    """Split findings into (active, waived).

    Each entry in the returned waived list is::

        {"finding": Finding, "waiver": dict}

    A waiver without both a ``reason`` and an ``author`` field is treated as
    unjustified: the finding is NOT suppressed.  Instead it is re-emitted as
    INFO with the note "waived without justification" so the engineer is forced
    to document the decision properly.
    """
    active: List[Finding] = []
    waived: List[Dict] = []

    for finding in findings:
        matched = _find_matching_waiver(finding, waivers)
        if matched:
            has_reason = bool(matched.get("reason", "").strip())
            has_author = bool(matched.get("author", "").strip())
            if has_reason and has_author:
                waived.append({"finding": finding, "waiver": matched})
            else:
                # Re-emit as INFO so the engineer can't silently suppress
                from dataclasses import replace
                re_emitted = replace(
                    finding,
                    severity=Severity.INFO,
                    message=(
                        f"{finding.message}  "
                        f"[waived without justification — add 'reason' and 'author' to waiver]"
                    ),
                )
                active.append(re_emitted)
        else:
            active.append(finding)

    return active, waived


def _find_matching_waiver(finding: Finding, waivers: List[Dict]) -> Dict | None:
    for w in waivers:
        if _matches(finding, w):
            return w
    return None


def _matches(finding: Finding, waiver: Dict) -> bool:
    """Return True if all specified waiver fields match the finding."""
    # check name
    if waiver.get("check") and waiver["check"] != finding.check_name:
        return False

    # exact id match
    if waiver.get("id") and waiver["id"] != finding.id:
        return False

    # net or affected token in affected list or message
    target = waiver.get("net") or waiver.get("affected") or ""
    if target:
        in_affected = target in finding.affected
        in_message  = target in finding.message
        if not in_affected and not in_message:
            return False

    return True
