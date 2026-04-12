"""Structural DRC checks.

All checks are registered via @register and auto-discovered when this
module is imported.
"""
from __future__ import annotations

import re
from typing import Dict, List, Set

from schem_review.checks.registry import register
from schem_review.model import Component, Finding, Net, Netlist, PinDirection, Severity

# ---------------------------------------------------------------------------
# Helpers shared across DRC checks
# ---------------------------------------------------------------------------

_NC_MARKERS: Set[str] = {"NC", "NOCONNECT", "NO_CONNECT", "UNCONNECTED"}

_GND_TOKENS: Set[str] = {"GND", "VSS", "GROUND", "AGND", "DGND", "PGND", "0V", "0"}


def _is_nc(net: str) -> bool:
    return net.upper().replace(" ", "").replace("_", "") in _NC_MARKERS


def _is_unconnected(net_name) -> bool:  # type: ignore[override]
    """True when the pin has no net (None or empty string)."""
    return not net_name or not net_name.strip()


def _is_ground_net(name: str) -> bool:
    u = name.upper().replace("_", "").replace("-", "")
    return u in _GND_TOKENS or any(u.startswith(g) for g in _GND_TOKENS)


def _is_power_net(name: str) -> bool:
    """Heuristic: positive supply rail, not ground."""
    if _is_ground_net(name):
        return False
    u = name.upper().replace("_", "")
    return any(tok in u for tok in ["VCC", "VDD", "VEE", "POWER", "PWR", "V3", "V5", "V12",
                                     "V15", "V18", "V25", "V33"])


def _refdes_number(refdes: str) -> int:
    """Extract trailing number from refdes for range comparisons."""
    m = re.search(r"(\d+)$", refdes)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# 1. Unconnected pins
# ---------------------------------------------------------------------------

@register("Flag component pins that have no net connection", category="DRC")
def unconnected_pins(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []
    for i, comp in enumerate(netlist.components.values()):
        for pin in comp.pins:
            if _is_unconnected(pin.net):
                findings.append(Finding(
                    id=f"unconnected_pins_{i}_{pin.number}",
                    check_name="unconnected_pins",
                    severity=Severity.ERROR,
                    message=(
                        f"{comp.refdes} pin {pin.number} ({pin.name or '?'}) "
                        f"is unconnected"
                    ),
                    affected=[comp.refdes],
                    sheet=comp.sheet,
                ))
    return findings


# ---------------------------------------------------------------------------
# 2. Floating inputs
# ---------------------------------------------------------------------------

_DRIVER_DIRS: Set[PinDirection] = {
    PinDirection.OUT, PinDirection.PWR, PinDirection.BIDIR,
    PinDirection.OC, PinDirection.TRISTATE,
}


@register("Detect input pins whose net has no driving output or power pin", category="DRC")
def floating_inputs(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []
    for net in netlist.nets.values():
        if not net.name or _is_nc(net.name):
            continue
        input_pins = [p for p in net.pins if p.direction == PinDirection.IN]
        if not input_pins:
            continue
        has_driver = any(p.direction in _DRIVER_DIRS for p in net.pins)
        if has_driver:
            continue
        # Power nets are implicitly driven
        if _is_power_net(net.name) or _is_ground_net(net.name):
            continue
        affected = sorted({p.component for p in input_pins})
        # Find sheet from the first input pin's component
        sheet = ""
        first_comp = netlist.components.get(input_pins[0].component)
        if first_comp:
            sheet = first_comp.sheet
        findings.append(Finding(
            id=f"floating_inputs_{net.name}",
            check_name="floating_inputs",
            severity=Severity.ERROR,
            message=f"Net '{net.name}' has input pin(s) but no driver (no OUT/PWR/BIDIR pin)",
            affected=affected,
            sheet=sheet,
        ))
    return findings


# ---------------------------------------------------------------------------
# 3. Power pin conflicts
# ---------------------------------------------------------------------------

@register(
    "Detect nets driven by more than one PWR-type pin (multiple power sources)",
    category="DRC",
)
def power_pin_conflicts(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []
    for net in netlist.nets.values():
        pwr_comps: Set[str] = set()
        for pin in net.pins:
            if pin.direction == PinDirection.PWR:
                pwr_comps.add(pin.component)
        # More than one component driving the same net with a PWR pin is suspicious
        if len(pwr_comps) > 1:
            findings.append(Finding(
                id=f"power_conflict_{net.name}",
                check_name="power_pin_conflicts",
                severity=Severity.ERROR,
                message=(
                    f"Net '{net.name}' has multiple PWR-type pins from: "
                    f"{', '.join(sorted(pwr_comps))}"
                ),
                affected=sorted(pwr_comps),
                sheet="",
            ))
    return findings


# ---------------------------------------------------------------------------
# 4. Missing decoupling caps
# ---------------------------------------------------------------------------

@register(
    "Flag ICs whose power pins lack a decoupling capacitor on the same power net",
    category="DRC",
)
def missing_decoupling_caps(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    # Gather capacitor net pairs: cap refdes -> frozenset of nets it spans
    caps: Dict[str, frozenset] = {}
    for refdes, comp in netlist.components.items():
        if refdes.upper().startswith("C"):
            nets = frozenset(p.net for p in comp.pins if p.net and not _is_nc(p.net))
            if nets:
                caps[refdes] = nets

    # Ground nets present in the design
    ground_nets: Set[str] = {n for n in netlist.nets if _is_ground_net(n)}

    # Find ICs
    for refdes, comp in netlist.components.items():
        if not refdes.upper().startswith("U"):
            continue

        pwr_nets: Set[str] = set()
        for pin in comp.pins:
            if (
                pin.net
                and not _is_nc(pin.net)
                and not _is_ground_net(pin.net)
                and (
                    pin.direction == PinDirection.PWR
                    or _is_power_net(pin.net)
                )
            ):
                pwr_nets.add(pin.net)

        ic_num = _refdes_number(refdes)

        for pwr_net in sorted(pwr_nets):
            # Check if any cap connects this power net to a ground net
            has_decap = any(
                pwr_net in cap_nets and bool(cap_nets & ground_nets)
                for cap_nets in caps.values()
            )
            if not has_decap:
                findings.append(Finding(
                    id=f"missing_decap_{refdes}_{pwr_net}",
                    check_name="missing_decoupling_caps",
                    severity=Severity.WARN,
                    message=(
                        f"{refdes} ({comp.part_number or '?'}) has no decoupling cap "
                        f"on power net '{pwr_net}'"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))
    return findings


# ---------------------------------------------------------------------------
# 5. Net naming consistency
# ---------------------------------------------------------------------------

def _normalize_net(name: str) -> str:
    """Strip punctuation, underscores, convert to uppercase for grouping."""
    return re.sub(r"[^A-Z0-9]", "", name.upper())


@register(
    "Detect nets that refer to the same rail but use inconsistent naming conventions",
    category="DRC",
)
def net_naming_consistency(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []
    groups: Dict[str, List[str]] = {}
    for net_name in netlist.nets:
        if not net_name:
            continue
        key = _normalize_net(net_name)
        if not key:
            continue
        groups.setdefault(key, []).append(net_name)

    for key, names in groups.items():
        if len(names) < 2:
            continue
        # Only flag if the names are genuinely distinct (not just casing)
        unique = sorted(set(names))
        if len(unique) < 2:
            continue
        findings.append(Finding(
            id=f"net_naming_{key}",
            check_name="net_naming_consistency",
            severity=Severity.WARN,
            message=(
                f"Inconsistent net naming — all normalize to '{key}': "
                f"{', '.join(unique)}"
            ),
            affected=unique,
            sheet="",
        ))
    return findings
