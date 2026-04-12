"""Check registry — decorator-based registration for check functions."""
from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional

from schem_review.model import Finding, Netlist, Severity

# Central registry: check_name -> metadata dict
_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register(description: str, category: str = "DRC") -> Callable:
    """Decorator that registers a check function.

    Usage::

        @register("Check for floating input pins", category="DRC")
        def floating_inputs(netlist: Netlist) -> list[Finding]:
            ...
    """
    def decorator(func: Callable[[Netlist], List[Finding]]) -> Callable:
        name = func.__name__
        _REGISTRY[name] = {
            "name": name,
            "func": func,
            "description": description,
            "category": category,
        }
        return func

    return decorator


def get_all_checks() -> List[Dict[str, Any]]:
    """Return all registered checks in insertion order."""
    return list(_REGISTRY.values())


def run_checks(
    netlist: Netlist,
    check_names: List[str],
    progress_cb: Optional[Callable[[str], None]] = None,
) -> List[Finding]:
    """Run the named checks against *netlist* and return all Findings.

    *progress_cb* is called with the check name just before each check runs,
    allowing the UI to update a progress indicator.
    """
    findings: List[Finding] = []
    for name in check_names:
        if name not in _REGISTRY:
            continue
        if progress_cb is not None:
            progress_cb(name)
        try:
            results = _REGISTRY[name]["func"](netlist)
            findings.extend(results)
        except Exception as exc:  # noqa: BLE001
            findings.append(
                Finding(
                    id=f"{name}_exc_{uuid.uuid4().hex[:6]}",
                    check_name=name,
                    severity=Severity.INFO,
                    message=f"Check raised an exception: {exc}",
                    affected=[],
                    sheet="",
                )
            )
    return findings
