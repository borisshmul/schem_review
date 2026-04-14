"""Integrity checks: voltage domain crossing, reset domain, power sequencing,
and SPI mode consistency.

All checks are registered via @register and auto-discovered when this module
is imported.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from schem_review.checks.registry import register
from schem_review.model import (
    Component, ComponentType, Finding, Netlist, PinDirection, Severity,
)

# ---------------------------------------------------------------------------
# Shared helpers (duplicated from other check modules to avoid circular imports)
# ---------------------------------------------------------------------------

_GND_TOKENS: Set[str] = {"GND", "VSS", "GROUND", "AGND", "DGND", "PGND", "0V"}
_PWR_TOKENS = {"VCC", "VDD", "VEE", "POWER", "PWR", "VBAT", "VREF",
               "V3", "V5", "V12", "V18", "V25", "V33"}


def _is_ground_net(name: str) -> bool:
    u = name.upper().replace("_", "").replace("-", "")
    return u in {t.replace("_", "") for t in _GND_TOKENS} or any(
        u.startswith(g.replace("_", "")) for g in _GND_TOKENS
    )


def _is_power_net(name: str) -> bool:
    if _is_ground_net(name):
        return False
    u = name.upper().replace("_", "")
    return any(tok in u for tok in _PWR_TOKENS)


def _is_signal_net(name: str) -> bool:
    return bool(name) and not _is_ground_net(name) and not _is_power_net(name)


# ---------------------------------------------------------------------------
# Voltage helpers
# ---------------------------------------------------------------------------

def _infer_voltage_from_name(name: str) -> Optional[float]:
    """Extract supply voltage from a net or rail name.

    Handles: 3V3, 1V8, 3.3V, 1.8V, VDD_3V3, VCC_1V8, +5V, 12V, V1V8, V3V3.
    Returns Volts as float, or None if not parseable.
    """
    # Pattern: digits V digits — e.g. 3V3, 1V8, 2V5
    m = re.search(r'(\d+)[Vv](\d+)', name)
    if m:
        v = float(f"{m.group(1)}.{m.group(2)}")
        if 0.5 <= v <= 60.0:
            return v

    # Pattern: decimal.V or intV — e.g. 3.3V, 1.8V, 5V, 12V
    m = re.search(r'(\d+(?:\.\d+)?)\s*[Vv](?!\w)', name)
    if m:
        v = float(m.group(1))
        if 0.5 <= v <= 60.0:
            return v

    return None


def _build_power_voltage_map(netlist: Netlist) -> Dict[str, float]:
    """Return {net_name: voltage} for all power nets with parseable voltages."""
    vmap: Dict[str, float] = {}
    for net_name in netlist.nets:
        if _is_power_net(net_name) or _is_ground_net(net_name):
            v = _infer_voltage_from_name(net_name)
            if v is not None:
                vmap[net_name] = v
    return vmap


def _comp_supply_voltage(
    comp: Component, voltage_map: Dict[str, float]
) -> Optional[float]:
    """Infer the primary supply voltage of a component from its PWR pins."""
    voltages = []
    for pin in comp.pins:
        if pin.net and pin.direction == PinDirection.PWR and not _is_ground_net(pin.net):
            v = voltage_map.get(pin.net)
            if v is not None:
                voltages.append(v)
    return max(voltages) if voltages else None


# Level-shifter / isolation device part-number keywords
_LEVEL_SHIFTER_RE = re.compile(
    r'TXS\d|LSF\d|GTL|SN74LVC|IRLML|MOSFET.*LS|CBTLV|'
    r'NTB\d|PI4ULS|PCA9306|NLSV|P82B|ADUM\d',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 1. Voltage domain crossing
# ---------------------------------------------------------------------------

@register(
    "Flag signal nets connecting components with different supply voltage domains "
    "and no level-shifter in path — silent latch-up risk",
    category="INTEGRITY",
)
def voltage_domain_crossing(netlist: Netlist) -> List[Finding]:
    """Detect cross-domain connections where supply voltages differ and no
    level-shifter, isolator, or buffer with different supply domains is present.

    Confidence is 0.75 because supply voltage is inferred from net names, not
    from verified datasheet data.
    """
    voltage_map = _build_power_voltage_map(netlist)
    if not voltage_map:
        return []  # no named supply rails to analyse

    # Build component → supply voltage
    comp_domain: Dict[str, float] = {}
    for refdes, comp in netlist.components.items():
        v = _comp_supply_voltage(comp, voltage_map)
        if v is not None:
            comp_domain[refdes] = v

    findings: List[Finding] = []

    for net in netlist.nets.values():
        if not _is_signal_net(net.name):
            continue

        # Collect voltage per component on this net (skip unknowns)
        domains: Dict[str, float] = {
            pin.component: comp_domain[pin.component]
            for pin in net.pins
            if pin.component in comp_domain
        }

        if len(set(domains.values())) < 2:
            continue  # all same domain or not enough info

        # Check for a level-shifter: a component on this net whose part number
        # matches known translation keywords
        net_comps = [
            netlist.components[p.component]
            for p in net.pins
            if p.component in netlist.components
        ]
        has_level_shifter = any(
            _LEVEL_SHIFTER_RE.search(c.part_number or "") for c in net_comps
        )
        if has_level_shifter:
            continue

        # Group by voltage so the message is readable
        domain_groups: Dict[float, List[str]] = {}
        for refdes, v in sorted(domains.items()):
            domain_groups.setdefault(v, []).append(refdes)

        domain_str = "  vs.  ".join(
            f"{v:.1f}V ({', '.join(sorted(refs))})"
            for v, refs in sorted(domain_groups.items())
        )
        findings.append(Finding(
            id=f"vdomain_cross_{net.name}",
            check_name="voltage_domain_crossing",
            severity=Severity.WARN,
            message=(
                f"Net '{net.name}' connects components from different voltage "
                f"domains with no level-shifter: {domain_str}"
            ),
            affected=sorted(domains.keys()),
            confidence=0.75,
        ))

    return findings


# ---------------------------------------------------------------------------
# 2. Reset domain analysis
# ---------------------------------------------------------------------------

_RESET_NET_RE = re.compile(
    r'(?:^|[_\-])(?:N?RESET|RST|NRST|XRST|RSTN|RSTB|RESETB|RESET_N|RST_N)(?:[_\-\d]|$)',
    re.IGNORECASE,
)
_ACTIVE_LOW_NET_RE = re.compile(
    r'(?:_N$|_B$|_BAR$|^N_|^/|^!|RESET_N|RST_N|NRST|RSTN|RSTB)',
    re.IGNORECASE,
)
_ACTIVE_LOW_PIN_RE = re.compile(
    r'(?:_N$|_B$|_BAR$|^N_|^/|^!)',
    re.IGNORECASE,
)


@register(
    "Validate reset nets: single driver, at least one receiver, consistent active polarity",
    category="INTEGRITY",
)
def reset_domain_analysis(netlist: Netlist) -> List[Finding]:
    """Check every RST/RESET net for:

    * Multiple hard drivers (push-pull OUT) on the same reset net → CRITICAL
    * Reset net with no driver at all → ERROR
    * Reset net that drives nothing → INFO
    * Active-polarity name mismatch between net and pin names → WARN
    """
    findings: List[Finding] = []

    reset_nets = [
        net_name for net_name in netlist.nets
        if _RESET_NET_RE.search(net_name)
    ]

    for net_name in reset_nets:
        net = netlist.nets[net_name]
        if not net.pins:
            continue

        drivers   = [p for p in net.pins if p.direction == PinDirection.OUT]
        oc_pins   = [p for p in net.pins if p.direction == PinDirection.OC]
        pwr_pins  = [p for p in net.pins if p.direction == PinDirection.PWR]
        receivers = [p for p in net.pins if p.direction in (PinDirection.IN, PinDirection.BIDIR)]

        # ── Multiple push-pull drivers → CRITICAL ──────────────────────────
        if len(drivers) > 1:
            involved = sorted({p.component for p in drivers})
            findings.append(Finding(
                id=f"reset_multi_driver_{net_name}",
                check_name="reset_domain_analysis",
                severity=Severity.CRITICAL,
                message=(
                    f"Reset net '{net_name}' is driven by {len(drivers)} push-pull "
                    f"outputs ({', '.join(involved)}) — contention will damage drivers"
                ),
                affected=involved,
            ))

        # ── No driver at all → ERROR ────────────────────────────────────────
        elif not drivers and not oc_pins and not pwr_pins:
            all_comps = sorted({p.component for p in net.pins})
            findings.append(Finding(
                id=f"reset_no_driver_{net_name}",
                check_name="reset_domain_analysis",
                severity=Severity.ERROR,
                message=(
                    f"Reset net '{net_name}' has no driver (no OUT/PWR/OC pin) — "
                    f"reset state is undefined; add a supervisor or RC circuit"
                ),
                affected=all_comps,
            ))

        # ── Driver with no receiver → INFO ──────────────────────────────────
        if (drivers or oc_pins or pwr_pins) and not receivers:
            driving = sorted({p.component for p in drivers + oc_pins + pwr_pins})
            findings.append(Finding(
                id=f"reset_no_receiver_{net_name}",
                check_name="reset_domain_analysis",
                severity=Severity.INFO,
                message=(
                    f"Reset net '{net_name}' has a driver ({', '.join(driving)}) "
                    f"but no receiver — possible incomplete connection or test-only net"
                ),
                affected=driving,
            ))

        # ── Polarity name mismatch ──────────────────────────────────────────
        net_is_active_low = bool(_ACTIVE_LOW_NET_RE.search(net_name))
        for pin in receivers:
            pin_is_active_low = bool(_ACTIVE_LOW_PIN_RE.search(pin.name))
            # Only flag when one side explicitly marks active-low and the other doesn't
            if net_is_active_low != pin_is_active_low and (
                net_is_active_low or pin_is_active_low
            ):
                comp = netlist.components.get(pin.component)
                sheet = comp.sheet if comp else ""
                findings.append(Finding(
                    id=f"reset_polarity_{net_name}_{pin.component}_{pin.number}",
                    check_name="reset_domain_analysis",
                    severity=Severity.WARN,
                    message=(
                        f"Reset polarity mismatch: net '{net_name}' "
                        f"({'active-low' if net_is_active_low else 'active-high'}) "
                        f"drives {pin.component} pin '{pin.name}' "
                        f"({'active-low' if pin_is_active_low else 'active-high'}) — "
                        f"device may never leave reset"
                    ),
                    affected=[pin.component],
                    sheet=sheet,
                    confidence=0.80,
                ))

    return findings


# ---------------------------------------------------------------------------
# 3. Power sequencing graph
# ---------------------------------------------------------------------------

_EN_PIN_RE = re.compile(
    r'^(?:EN|ENABLE|PWR_EN|VREG_EN|LDO_EN|SHDN_N|SHDN|SD_N|SD|ON_N|ON)$',
    re.IGNORECASE,
)


def _dfs_cycle(
    graph: Dict[str, List[str]],
    node: str,
    visited: Set[str],
    stack: List[str],
) -> Optional[List[str]]:
    """Return the cycle path if one is reachable from node, else None."""
    visited.add(node)
    stack.append(node)
    for neighbor in graph.get(node, []):
        if neighbor in stack:
            # Found a cycle — return the cycle portion of the stack
            cycle_start = stack.index(neighbor)
            return stack[cycle_start:] + [neighbor]
        if neighbor not in visited:
            result = _dfs_cycle(graph, neighbor, visited, stack)
            if result:
                return result
    stack.pop()
    return None


@register(
    "Build power enable-chain graph; flag cycles (latch conditions) and unsequenced rails",
    category="INTEGRITY",
)
def power_sequencing(netlist: Netlist) -> List[Finding]:
    """Detect power sequencing issues:

    * Cycle in the enable graph (A enables B which enables A) → CRITICAL
    * Regulator EN pin tied directly to a power rail (no sequencing) → INFO
    """
    findings: List[Finding] = []

    regulators = {
        r: c for r, c in netlist.components.items()
        if c.component_type == ComponentType.REGULATOR
    }
    if len(regulators) < 2:
        return []

    # Build enable graph: regulator refdes → list of refdes that control its EN pin
    enable_graph: Dict[str, List[str]] = {}

    for refdes, comp in regulators.items():
        en_pin = next(
            (p for p in comp.pins if _EN_PIN_RE.match(p.name)),
            None,
        )
        if en_pin is None or not en_pin.net:
            continue

        # Check if EN is tied directly to a power net (no sequencing)
        if _is_power_net(en_pin.net):
            findings.append(Finding(
                id=f"pwr_seq_no_sequence_{refdes}",
                check_name="power_sequencing",
                severity=Severity.INFO,
                message=(
                    f"{refdes} EN pin is tied directly to '{en_pin.net}' — "
                    f"rail powers up with no sequencing delay; add a supervisor "
                    f"or PGOOD chain if sequencing is required"
                ),
                affected=[refdes],
                sheet=comp.sheet,
                confidence=0.90,
            ))
            continue

        # Find OUT/PWR drivers on the EN net (other than this regulator itself)
        en_net = netlist.nets.get(en_pin.net)
        if not en_net:
            continue
        drivers = [
            p.component for p in en_net.pins
            if p.component != refdes
            and p.direction in (PinDirection.OUT, PinDirection.PWR)
            and p.component in regulators
        ]
        if drivers:
            enable_graph[refdes] = drivers

    # Detect cycles
    visited: Set[str] = set()
    reported_cycles: Set[frozenset] = set()

    for start in list(enable_graph.keys()):
        if start in visited:
            continue
        cycle = _dfs_cycle(enable_graph, start, visited, [])
        if cycle:
            key = frozenset(cycle)
            if key not in reported_cycles:
                reported_cycles.add(key)
                findings.append(Finding(
                    id=f"pwr_seq_cycle_{'_'.join(sorted(set(cycle)))}",
                    check_name="power_sequencing",
                    severity=Severity.CRITICAL,
                    message=(
                        f"Power sequencing cycle: {' → '.join(cycle)} — "
                        f"this latch condition will prevent any rail from starting"
                    ),
                    affected=sorted(set(cycle)),
                    confidence=0.85,
                ))

    return findings


# ---------------------------------------------------------------------------
# 4. SPI mode consistency
# ---------------------------------------------------------------------------

_SCK_PIN_RE  = re.compile(r'^(?:SCK|SCLK|CLK|SPICLK)$', re.IGNORECASE)
_CPOL_PIN_RE = re.compile(r'^CPOL$', re.IGNORECASE)
_CPHA_PIN_RE = re.compile(r'^CPHA$', re.IGNORECASE)


def _pin_logic_level(pin_net: str, netlist: Netlist) -> Optional[int]:
    """Return 0 if pin_net is a ground net, 1 if power net, None if unknown."""
    if _is_ground_net(pin_net):
        return 0
    if _is_power_net(pin_net):
        return 1
    # Could be a pull-up/pull-down — try to infer from resistor topology
    net = netlist.nets.get(pin_net)
    if not net:
        return None
    for pin in net.pins:
        comp = netlist.components.get(pin.component)
        if comp and comp.component_type == ComponentType.RESISTOR:
            other_nets = [p.net for p in comp.pins if p.net and p.net != pin_net]
            for n in other_nets:
                if _is_ground_net(n):
                    return 0
                if _is_power_net(n):
                    return 1
    return None


@register(
    "Detect SPI bus members with mismatched CPOL/CPHA mode settings "
    "— master and slaves will never transfer data",
    category="INTEGRITY",
)
def spi_mode_consistency(netlist: Netlist) -> List[Finding]:
    """Group SPI devices by shared SCK net; for each bus check that all devices
    with explicit CPOL/CPHA pins agree on the mode.

    Confidence is 0.80 because CPOL/CPHA are sometimes set in firmware and may
    not appear as schematic pins.
    """
    findings: List[Finding] = []

    # Map: SCK net → list of components that share it
    sck_bus: Dict[str, List[Component]] = {}
    for comp in netlist.components.values():
        for pin in comp.pins:
            if _SCK_PIN_RE.match(pin.name) and pin.net:
                if not _is_power_net(pin.net) and not _is_ground_net(pin.net):
                    sck_bus.setdefault(pin.net, []).append(comp)

    for sck_net, bus_comps in sck_bus.items():
        if len(bus_comps) < 2:
            continue

        # For each component on the bus, determine CPOL and CPHA states
        cpol_states: Dict[str, Optional[int]] = {}
        cpha_states: Dict[str, Optional[int]] = {}

        for comp in bus_comps:
            cpol_pin = next((p for p in comp.pins if _CPOL_PIN_RE.match(p.name)), None)
            cpha_pin = next((p for p in comp.pins if _CPHA_PIN_RE.match(p.name)), None)

            if cpol_pin and cpol_pin.net:
                cpol_states[comp.refdes] = _pin_logic_level(cpol_pin.net, netlist)
            if cpha_pin and cpha_pin.net:
                cpha_states[comp.refdes] = _pin_logic_level(cpha_pin.net, netlist)

        def _check_mismatch(
            states: Dict[str, Optional[int]],
            kind: str,
        ) -> None:
            known = {r: v for r, v in states.items() if v is not None}
            if len(known) < 2:
                return
            values = set(known.values())
            if len(values) > 1:
                detail = ", ".join(
                    f"{r}={v}" for r, v in sorted(known.items())
                )
                findings.append(Finding(
                    id=f"spi_mode_mismatch_{kind}_{sck_net}",
                    check_name="spi_mode_consistency",
                    severity=Severity.ERROR,
                    message=(
                        f"SPI bus (SCK: '{sck_net}') has mixed {kind} settings "
                        f"({detail}) — master and slaves are in different modes "
                        f"and will never complete a transaction"
                    ),
                    affected=sorted(known.keys()),
                    confidence=0.80,
                ))

        _check_mismatch(cpol_states, "CPOL")
        _check_mismatch(cpha_states, "CPHA")

    return findings
