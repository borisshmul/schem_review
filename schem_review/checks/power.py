"""Power system checks.

Covers: LED current limiting, switching regulator completeness,
bulk capacitance, VDDA/analog isolation, decoupling hierarchy,
and ESD protection on external ports.
"""
from __future__ import annotations

import re
from typing import Dict, List, Set

from schem_review.checks.registry import register
from schem_review.model import (
    Component, ComponentType, Finding, Net, Netlist, PinDirection, Severity,
)

# ---------------------------------------------------------------------------
# Shared helpers
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


def _comps_on_net(net_name: str, netlist: Netlist) -> List[Component]:
    """Return all Component objects whose pins touch net_name."""
    net = netlist.nets.get(net_name)
    if not net:
        return []
    result = []
    seen: Set[str] = set()
    for pin in net.pins:
        if pin.component not in seen:
            seen.add(pin.component)
            comp = netlist.components.get(pin.component)
            if comp:
                result.append(comp)
    return result


def _has_type_on_net(net_name: str, netlist: Netlist, ctype: ComponentType) -> bool:
    return any(c.component_type == ctype for c in _comps_on_net(net_name, netlist))


def _caps_on_net_with_gnd(net_name: str, netlist: Netlist) -> List[Component]:
    """Return capacitors that bridge net_name to a ground net."""
    ground_nets = {n for n in netlist.nets if _is_ground_net(n)}
    result = []
    for comp in netlist.components.values():
        if comp.component_type != ComponentType.CAPACITOR:
            continue
        comp_nets = {p.net for p in comp.pins if p.net}
        if net_name in comp_nets and comp_nets & ground_nets:
            result.append(comp)
    return result


def _sheet_of(refdes: str, netlist: Netlist) -> str:
    comp = netlist.components.get(refdes)
    return comp.sheet if comp else ""


# ---------------------------------------------------------------------------
# 1. LED missing current-limiting resistor
# ---------------------------------------------------------------------------

@register(
    "CRITICAL: LED with a direct driver and no series current-limiting resistor",
    category="POWER",
)
def led_missing_current_limit(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []
    for refdes, comp in netlist.components.items():
        if comp.component_type != ComponentType.LED:
            continue

        for pin in comp.pins:
            if not pin.net:
                continue
            # Cathode usually goes to GND — skip GND and power rails
            if _is_ground_net(pin.net) or _is_power_net(pin.net):
                continue

            net = netlist.nets.get(pin.net)
            if not net:
                continue

            other_comps = [
                netlist.components[p.component]
                for p in net.pins
                if p.component != refdes and p.component in netlist.components
            ]

            has_driver   = any(
                p.direction in (PinDirection.OUT, PinDirection.PWR)
                for p in net.pins
                if p.component != refdes
            )
            has_resistor = any(
                c.component_type == ComponentType.RESISTOR
                for c in other_comps
            )

            if has_driver and not has_resistor:
                findings.append(Finding(
                    id=f"led_no_resistor_{refdes}_{pin.number}",
                    check_name="led_missing_current_limit",
                    severity=Severity.CRITICAL,
                    message=(
                        f"{refdes} ({comp.part_number}) has a direct driver on "
                        f"net '{pin.net}' with no current-limiting resistor — "
                        f"will damage the LED and likely the driving pin"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))
                break  # one finding per LED

    return findings


# ---------------------------------------------------------------------------
# 2. Switching regulator completeness
# ---------------------------------------------------------------------------

_SW_PIN_NAMES:  Set[str] = {"SW", "SW1", "SW2", "LX", "SWITCH", "PH", "BOOST"}
_FB_PIN_NAMES:  Set[str] = {"FB", "FBK", "SENSE", "VSENSE", "VFEEDBACK"}
_VIN_PIN_NAMES: Set[str] = {"VIN", "VIN1", "VIN2", "INPUT", "VI", "IN"}


@register(
    "CRITICAL/ERROR: Switching regulator missing inductor, feedback divider, or input cap",
    category="POWER",
)
def switching_regulator_completeness(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    ground_nets: Set[str] = {n for n in netlist.nets if _is_ground_net(n)}

    for refdes, comp in netlist.components.items():
        if comp.component_type != ComponentType.REGULATOR:
            continue

        pin_names_upper = {p.name.upper(): p for p in comp.pins}

        # ── SW / inductor check ─────────────────────────────────────────────
        sw_pin = next(
            (p for name, p in pin_names_upper.items() if name in _SW_PIN_NAMES),
            None,
        )
        if sw_pin and sw_pin.net:
            has_inductor = _has_type_on_net(sw_pin.net, netlist, ComponentType.INDUCTOR)
            if not has_inductor:
                findings.append(Finding(
                    id=f"reg_no_inductor_{refdes}",
                    check_name="switching_regulator_completeness",
                    severity=Severity.CRITICAL,
                    message=(
                        f"{refdes} ({comp.part_number}) SW pin is on net '{sw_pin.net}' "
                        f"but no inductor (L-prefixed) is connected — "
                        f"output voltage will be unregulated"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))

        # ── FB / feedback divider check ─────────────────────────────────────
        fb_pin = next(
            (p for name, p in pin_names_upper.items() if name in _FB_PIN_NAMES),
            None,
        )
        if fb_pin and fb_pin.net:
            comps_on_fb = _comps_on_net(fb_pin.net, netlist)
            resistors_on_fb = [c for c in comps_on_fb
                               if c.component_type == ComponentType.RESISTOR
                               and c.refdes != refdes]
            if not resistors_on_fb:
                findings.append(Finding(
                    id=f"reg_no_feedback_{refdes}",
                    check_name="switching_regulator_completeness",
                    severity=Severity.CRITICAL,
                    message=(
                        f"{refdes} ({comp.part_number}) FB pin is on net '{fb_pin.net}' "
                        f"with no feedback resistor — output voltage is undefined"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))

        # ── VIN input capacitor check ────────────────────────────────────────
        vin_pin = next(
            (p for name, p in pin_names_upper.items() if name in _VIN_PIN_NAMES),
            None,
        )
        if vin_pin and vin_pin.net:
            input_caps = _caps_on_net_with_gnd(vin_pin.net, netlist)
            if not input_caps:
                findings.append(Finding(
                    id=f"reg_no_input_cap_{refdes}",
                    check_name="switching_regulator_completeness",
                    severity=Severity.ERROR,
                    message=(
                        f"{refdes} ({comp.part_number}) VIN pin (net '{vin_pin.net}') "
                        f"has no input bypass capacitor to ground — "
                        f"regulator may oscillate or latch up"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))

    return findings


# ---------------------------------------------------------------------------
# 3. Missing bulk capacitance on power input connector
# ---------------------------------------------------------------------------

_BULK_THRESHOLD_F = 10e-6   # 10 µF

@register(
    "Power input connector has no bulk capacitance (≥10 µF) on the input rail",
    category="POWER",
)
def bulk_cap_on_power_input(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    for refdes, comp in netlist.components.items():
        if comp.component_type != ComponentType.CONNECTOR:
            continue

        # Collect power (non-GND) nets on this connector
        pwr_nets: Set[str] = set()
        for pin in comp.pins:
            if pin.net and not _is_ground_net(pin.net) and _is_power_net(pin.net):
                pwr_nets.add(pin.net)
            elif pin.net and not _is_ground_net(pin.net):
                # Also include nets that look like VIN/VCC/PWR even if not matching heuristic
                if any(kw in pin.net.upper() for kw in ("VIN", "V_IN", "SUPPLY", "VBUS")):
                    pwr_nets.add(pin.net)

        for net_name in sorted(pwr_nets):
            caps = _caps_on_net_with_gnd(net_name, netlist)
            # Filter: must be ≥ 10 µF (value known) or any cap if value unknown
            bulk_caps = [
                c for c in caps
                if c.value is None or c.value >= _BULK_THRESHOLD_F
            ]
            if not bulk_caps:
                findings.append(Finding(
                    id=f"bulk_cap_{refdes}_{net_name}",
                    check_name="bulk_cap_on_power_input",
                    severity=Severity.WARN,
                    message=(
                        f"Power input net '{net_name}' (via {refdes}) has no bulk "
                        f"capacitance ≥10 µF — supply is vulnerable to transient "
                        f"droop on step loads"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))

    return findings


# ---------------------------------------------------------------------------
# 4. VDDA / analog supply isolation
# ---------------------------------------------------------------------------

_ANALOG_PIN_RE = re.compile(
    r'^(VDDA|VDDIO|AVDD|AVCC|VREF|VDDA\d*|AVDD\d*|AVCC\d*|VREF\d*|VREFP|VAIN)$',
    re.IGNORECASE,
)
_DIGITAL_PWR_PIN_RE = re.compile(
    r'^(VDD|VCC|DVDD|DVCC|VCORE|VDD\d+|VCC\d+)$',
    re.IGNORECASE,
)


@register(
    "VDDA/AVDD analog supply shares net with digital VDD with no ferrite-bead isolation",
    category="POWER",
)
def vdda_isolation(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    for refdes, comp in netlist.components.items():
        if comp.component_type not in (ComponentType.IC, ComponentType.REGULATOR):
            continue

        analog_nets: Set[str] = set()
        digital_nets: Set[str] = set()

        for pin in comp.pins:
            if not pin.net:
                continue
            if _ANALOG_PIN_RE.match(pin.name):
                analog_nets.add(pin.net)
            elif _DIGITAL_PWR_PIN_RE.match(pin.name):
                digital_nets.add(pin.net)

        # Flag when analog and digital pins land on the *same* net
        shared = analog_nets & digital_nets
        for net_name in sorted(shared):
            # Check if a ferrite bead exists anywhere between the two domains
            has_ferrite = _has_type_on_net(net_name, netlist, ComponentType.FERRITE)
            if not has_ferrite:
                findings.append(Finding(
                    id=f"vdda_no_isolation_{refdes}_{net_name}",
                    check_name="vdda_isolation",
                    severity=Severity.WARN,
                    message=(
                        f"{refdes}: analog supply pin (VDDA/AVDD) and digital supply "
                        f"pin (VDD/VCC) both land on '{net_name}' with no ferrite-bead "
                        f"isolation — analog noise floor will be compromised"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                    confidence=0.85,
                ))

    return findings


# ---------------------------------------------------------------------------
# 5. Decoupling hierarchy (4 tiers)
# ---------------------------------------------------------------------------

_BULK_F     = 47e-6    # Tier 1: ≥ 47 µF bulk per rail
_BYPASS_F   = 10e-9   # Tier 2: ≥ 10 nF local bypass (caps without value pass)
_HF_F       = 10e-9   # Tier 3: ≤ 10 nF high-freq for analog pins


@register(
    "Decoupling hierarchy: flag power rails missing bulk cap or analog pins missing HF bypass",
    category="POWER",
)
def decoupling_hierarchy(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    # Collect all power rails and their associated capacitors
    power_rails: Set[str] = {n for n in netlist.nets if _is_power_net(n)}

    # Tier 1: each power rail needs at least one cap ≥ 47 µF
    for rail in sorted(power_rails):
        caps = _caps_on_net_with_gnd(rail, netlist)
        bulk_caps = [c for c in caps if c.value is not None and c.value >= _BULK_F]
        unknown_caps = [c for c in caps if c.value is None]  # can't rule out bulk
        if not bulk_caps and not unknown_caps:
            findings.append(Finding(
                id=f"decap_no_bulk_{rail}",
                check_name="decoupling_hierarchy",
                severity=Severity.WARN,
                message=(
                    f"Power rail '{rail}' has no bulk capacitor ≥47 µF — "
                    f"Tier 1 (charge reservoir) is missing; supply will droop "
                    f"under step-load transients"
                ),
                affected=[rail],
                confidence=0.8,
            ))

    # Tier 3: analog supply pins need an HF bypass cap (≤ 10 nF)
    for refdes, comp in netlist.components.items():
        if comp.component_type not in (ComponentType.IC, ComponentType.REGULATOR):
            continue
        for pin in comp.pins:
            if not pin.net or not _ANALOG_PIN_RE.match(pin.name):
                continue
            caps = _caps_on_net_with_gnd(pin.net, netlist)
            hf_caps = [c for c in caps if c.value is not None and c.value <= _HF_F]
            if not hf_caps:
                findings.append(Finding(
                    id=f"decap_no_hf_{refdes}_{pin.name}",
                    check_name="decoupling_hierarchy",
                    severity=Severity.WARN,
                    message=(
                        f"{refdes} analog pin '{pin.name}' (net '{pin.net}') has no "
                        f"high-frequency bypass cap ≤10 nF — "
                        f"Tier 3 (HF decoupling for analog supply) is missing"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                    confidence=0.8,
                ))

    # Tier 4: VDDA-style pins with no ferrite (already covered by vdda_isolation)
    # Cross-reference only: if vdda_isolation fires on a comp, note Tier 4 gap

    return findings


# ---------------------------------------------------------------------------
# 6. ESD protection on external-facing nets
# ---------------------------------------------------------------------------

# Part-number keywords that identify ESD / TVS protection devices
_ESD_PART_RE = re.compile(
    r'TVS|PRTR|USBLC|CDSOT|ESDA|SMBJ|P6KE|P4KE|SMAJ|'
    r'ESD\d|TPD\d|RCLAMP|SRV\d|SRVS|LESD|SP\d{4}',
    re.IGNORECASE,
)

# High-risk signal nets that should have ESD protection on external connectors
_HIGH_RISK_NET_RE = re.compile(
    r'USB|ETH|CAN|LIN|RS232|RS485|UART|VBUS|ENET|'
    r'SDA|SCL|MOSI|MISO|SCK|SPI|JTAG|SWD|SWDIO|SWDCLK|NRST',
    re.IGNORECASE,
)


@register(
    "External connector pins lack ESD/TVS protection on high-risk or high-speed nets",
    category="POWER",
)
def esd_protection_external(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    # Find connectors
    for refdes, comp in netlist.components.items():
        if comp.component_type != ComponentType.CONNECTOR:
            continue

        for pin in comp.pins:
            if not pin.net:
                continue
            if _is_ground_net(pin.net) or _is_power_net(pin.net):
                continue
            # Only flag high-risk signal nets
            if not _HIGH_RISK_NET_RE.search(pin.net):
                continue

            # Check if any ESD/TVS device is on this net
            net_comps = _comps_on_net(pin.net, netlist)
            has_esd = any(
                _ESD_PART_RE.search(c.part_number or "")
                or (c.component_type == ComponentType.DIODE
                    and _ESD_PART_RE.search(c.part_number or ""))
                for c in net_comps
            )

            if not has_esd:
                findings.append(Finding(
                    id=f"esd_missing_{refdes}_{pin.net}",
                    check_name="esd_protection_external",
                    severity=Severity.ERROR,
                    message=(
                        f"Connector {refdes} pin '{pin.name}' is on net '{pin.net}' — "
                        f"no ESD/TVS protection device found on this external net"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                    confidence=0.9,
                ))

    return findings
