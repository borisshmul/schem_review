"""Ethernet / high-speed link checks: SGMII, RGMII, MDI, MDIO, and PHY power.

All checks are registered via @register and auto-discovered when this
module is imported.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from schem_review.checks.registry import register
from schem_review.model import Finding, Netlist, PinDirection, Severity

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_GND_TOKENS: Set[str] = {"GND", "VSS", "GROUND", "AGND", "DGND", "PGND", "0V"}
_AGND_TOKENS: Set[str] = {"AGND", "AGND1", "AVSS"}
_DGND_TOKENS: Set[str] = {"DGND", "DVSS", "GND", "VSS", "PGND"}


def _is_ground_net(name: str) -> bool:
    u = name.upper().replace("_", "").replace("-", "")
    return u in {t.replace("_", "") for t in _GND_TOKENS} or any(
        u.startswith(g.replace("_", "")) for g in _GND_TOKENS
    )


def _is_power_net(name: str) -> bool:
    if _is_ground_net(name):
        return False
    u = name.upper().replace("_", "")
    return any(
        tok in u
        for tok in ["VCC", "VDD", "VEE", "POWER", "PWR", "VBAT", "VREF",
                    "V3", "V5", "V12", "V18", "V25", "V33"]
    )


def _nets_matching(netlist: Netlist, pattern: str, flags: int = re.IGNORECASE) -> List[str]:
    rx = re.compile(pattern, flags)
    return [n for n in netlist.nets if rx.search(n)]


def _resistors_on_net(net_name: str, netlist: Netlist) -> List[str]:
    """Return refdes of resistors with a pin on net_name."""
    result = []
    for refdes, comp in netlist.components.items():
        if not refdes.upper().startswith("R"):
            continue
        if any(p.net == net_name for p in comp.pins):
            result.append(refdes)
    return result


def _caps_on_net(net_name: str, netlist: Netlist) -> List[str]:
    """Return refdes of capacitors with a pin on net_name."""
    result = []
    for refdes, comp in netlist.components.items():
        if not refdes.upper().startswith("C"):
            continue
        if any(p.net == net_name for p in comp.pins):
            result.append(refdes)
    return result


def _resistors_bridging(net_a: str, net_b: str, netlist: Netlist) -> List[str]:
    """Return resistors that have one pin on net_a and another on net_b."""
    result = []
    for refdes, comp in netlist.components.items():
        if not refdes.upper().startswith("R"):
            continue
        comp_nets = {p.net for p in comp.pins if p.net}
        if net_a in comp_nets and net_b in comp_nets:
            result.append(refdes)
    return result


def _caps_in_series(net_name: str, netlist: Netlist) -> List[str]:
    """Return caps that have exactly one pin on net_name (series AC coupling)."""
    result = []
    for refdes, comp in netlist.components.items():
        if not refdes.upper().startswith("C"):
            continue
        nets_here = [p.net for p in comp.pins if p.net]
        if nets_here.count(net_name) == 1 and len(set(nets_here)) == 2:
            result.append(refdes)
    return result


def _diff_base(name: str, p_re: "re.Pattern", n_re: "re.Pattern") -> Tuple[Optional[str], str]:
    """Return (base_name_upper, 'P'|'N') if net matches a diff suffix, else (None, '')."""
    if p_re.search(name):
        return p_re.sub("", name).upper(), "P"
    if n_re.search(name):
        return n_re.sub("", name).upper(), "N"
    return None, ""


_DIFF_P_RE = re.compile(r"(_P|_POS|\+)$", re.IGNORECASE)
_DIFF_N_RE = re.compile(r"(_N|_NEG|-)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 1. SGMII / SerDes differential pair integrity
# ---------------------------------------------------------------------------

_SGMII_RE = re.compile(r"SGMII|SERDES|SER_?DES|TXSER|RXSER|TX_SER|RX_SER", re.IGNORECASE)
_HS_DIFF_P_RE = re.compile(r"[_\-]?P$|\+$|_POS$", re.IGNORECASE)
_HS_DIFF_N_RE = re.compile(r"[_\-]?N$|-$|_NEG$", re.IGNORECASE)


@register(
    "SGMII/SerDes: verify both P/N sides present and AC-coupling caps on each lane",
    category="SGMII",
)
def sgmii_differential_pairs(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    # Collect SGMII-looking nets (and any SerDes-named diff pair)
    candidate_nets = _nets_matching(netlist, r"SGMII|SERDES|SER_?DES|TX_SER|RX_SER|"
                                             r"(?:ETH|PHY|MAC)_?(?:TX|RX)[_\-]?[PN01]")

    if not candidate_nets:
        # Fall back to any HS diff-named nets near TX/RX
        candidate_nets = _nets_matching(
            netlist,
            r"(?:TX|RX)[_\-]?(?:P|N|POS|NEG|\+|-)$"
        )
    if not candidate_nets:
        return findings

    # Group into P/N pairs by stripping the suffix
    bases_p: Dict[str, str] = {}
    bases_n: Dict[str, str] = {}
    for net in candidate_nets:
        base, side = _diff_base(net, _HS_DIFF_P_RE, _HS_DIFF_N_RE)
        if base is None:
            continue
        if side == "P":
            bases_p[base] = net
        else:
            bases_n[base] = net

    all_bases = set(bases_p) | set(bases_n)
    for base in sorted(all_bases):
        p_net = bases_p.get(base)
        n_net = bases_n.get(base)

        if p_net and not n_net:
            findings.append(Finding(
                id=f"sgmii_missing_n_{base}",
                check_name="sgmii_differential_pairs",
                severity=Severity.ERROR,
                message=f"SerDes/SGMII pair '{base}': P net '{p_net}' has no N counterpart",
                affected=[p_net],
            ))
        elif n_net and not p_net:
            findings.append(Finding(
                id=f"sgmii_missing_p_{base}",
                check_name="sgmii_differential_pairs",
                severity=Severity.ERROR,
                message=f"SerDes/SGMII pair '{base}': N net '{n_net}' has no P counterpart",
                affected=[n_net],
            ))
        else:
            # Both sides present — check AC-coupling caps on each side
            for net in (p_net, n_net):
                if not _caps_in_series(net, netlist):
                    findings.append(Finding(
                        id=f"sgmii_no_ac_cap_{net}",
                        check_name="sgmii_differential_pairs",
                        severity=Severity.WARN,
                        message=(
                            f"SerDes/SGMII net '{net}' has no series AC-coupling "
                            f"capacitor — required for DC isolation"
                        ),
                        affected=[net],
                    ))

    return findings


@register(
    "SGMII/SerDes: verify DC bias resistors on AC-coupled lanes",
    category="SGMII",
)
def sgmii_dc_bias(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    # AC-coupled SerDes lines need a DC-bias resistor (typically to VDD/2 or VTERM)
    # Heuristic: caps in series on diff-pair nets, no resistor to a power or bias net
    candidate_nets = _nets_matching(
        netlist,
        r"(?:TX|RX)[_\-]?(?:P|N|POS|NEG)$|SGMII|SERDES",
    )
    if not candidate_nets:
        return findings

    for net in candidate_nets:
        series_caps = _caps_in_series(net, netlist)
        if not series_caps:
            continue  # Not AC-coupled — bias check not applicable
        # Check that there is at least one resistor connecting this net to a power
        # or bias rail (DC restoration)
        resistors = _resistors_on_net(net, netlist)
        has_bias = False
        for r in resistors:
            comp = netlist.components.get(r)
            if not comp:
                continue
            other_nets = {p.net for p in comp.pins if p.net and p.net != net}
            if any(_is_power_net(on) for on in other_nets):
                has_bias = True
                break
        if not has_bias:
            findings.append(Finding(
                id=f"sgmii_no_dc_bias_{net}",
                check_name="sgmii_dc_bias",
                severity=Severity.WARN,
                message=(
                    f"AC-coupled SerDes net '{net}' has no DC-bias resistor to a "
                    f"supply rail — add bias for correct common-mode voltage"
                ),
                affected=[net],
            ))

    return findings


@register(
    "SGMII/SerDes: check line termination resistors (100 Ω differential or 50 Ω each side)",
    category="SGMII",
)
def sgmii_termination(netlist: Netlist) -> List[Finding]:
    """
    Checks that each SGMII/SerDes diff pair has either:
      - A 100 Ω resistor bridging P and N (differential termination), OR
      - Individual resistors on each P and N net to a supply/ground
    """
    findings: List[Finding] = []

    bases_p: Dict[str, str] = {}
    bases_n: Dict[str, str] = {}

    candidate_nets = _nets_matching(
        netlist,
        r"(?:TX|RX)[_\-]?(?:P|N|POS|NEG)$|SGMII|SERDES",
    )
    for net in candidate_nets:
        base, side = _diff_base(net, _HS_DIFF_P_RE, _HS_DIFF_N_RE)
        if base is None:
            continue
        if side == "P":
            bases_p[base] = net
        else:
            bases_n[base] = net

    all_bases = set(bases_p) & set(bases_n)  # only complete pairs
    for base in sorted(all_bases):
        p_net = bases_p[base]
        n_net = bases_n[base]

        # Check differential termination (resistor between P and N)
        diff_term = _resistors_bridging(p_net, n_net, netlist)
        if diff_term:
            continue  # differential termination present

        # Check individual terminations
        p_term = _resistors_on_net(p_net, netlist)
        n_term = _resistors_on_net(n_net, netlist)
        if not p_term or not n_term:
            missing = []
            if not p_term:
                missing.append(p_net)
            if not n_term:
                missing.append(n_net)
            findings.append(Finding(
                id=f"sgmii_no_termination_{base}",
                check_name="sgmii_termination",
                severity=Severity.WARN,
                message=(
                    f"SerDes pair '{base}' has no termination resistor — "
                    f"missing on: {', '.join(missing)}"
                ),
                affected=[p_net, n_net],
            ))

    return findings


@register(
    "SGMII/SerDes: detect polarity swap (P and N pins connected to opposite nets)",
    category="SGMII",
)
def sgmii_polarity_swap(netlist: Netlist) -> List[Finding]:
    """
    Flag components whose P-named pin connects to an *_N net, or whose
    N-named pin connects to a *_P net.
    """
    findings: List[Finding] = []

    for refdes, comp in netlist.components.items():
        for pin in comp.pins:
            if not pin.net or not pin.name:
                continue
            pin_upper = pin.name.upper()
            net_upper = pin.net.upper()

            # Pin explicitly named P/POS but connected to an N/NEG net
            p_pin = re.search(r"[_\-]?P$|[_\-]?POS$|\+$", pin_upper)
            n_net = re.search(r"[_\-]N$|[_\-]NEG$|-$", net_upper)
            if p_pin and n_net:
                findings.append(Finding(
                    id=f"sgmii_polarity_swap_{refdes}_{pin.number}",
                    check_name="sgmii_polarity_swap",
                    severity=Severity.ERROR,
                    message=(
                        f"{refdes} pin '{pin.name}' (P-polarity) is connected to "
                        f"net '{pin.net}' which looks like an N-polarity net — "
                        f"probable polarity swap"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))
                continue

            # Pin explicitly named N/NEG but connected to a P/POS net
            n_pin = re.search(r"[_\-]?N$|[_\-]?NEG$|-$", pin_upper)
            p_net = re.search(r"[_\-]P$|[_\-]POS$|\+$", net_upper)
            if n_pin and p_net:
                findings.append(Finding(
                    id=f"sgmii_polarity_swap_{refdes}_{pin.number}",
                    check_name="sgmii_polarity_swap",
                    severity=Severity.ERROR,
                    message=(
                        f"{refdes} pin '{pin.name}' (N-polarity) is connected to "
                        f"net '{pin.net}' which looks like a P-polarity net — "
                        f"probable polarity swap"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))

    return findings


# ---------------------------------------------------------------------------
# 2. RGMII parallel interface
# ---------------------------------------------------------------------------

_RGMII_TX_SIGNALS = ["TXD0", "TXD1", "TXD2", "TXD3", "TX_CLK", "TX_CTL", "TXEN", "TXCLK"]
_RGMII_RX_SIGNALS = ["RXD0", "RXD1", "RXD2", "RXD3", "RX_CLK", "RX_CTL", "RXDV", "RXCLK"]
_RGMII_REQUIRED_TX = {"TXD0", "TXD1", "TXD2", "TXD3"}
_RGMII_REQUIRED_RX = {"RXD0", "RXD1", "RXD2", "RXD3"}
_RGMII_RE = re.compile(r"RGMII|(?:^|_)TXD[0-3]|(?:^|_)RXD[0-3]|TX_CLK|RX_CLK|TX_CTL|RX_CTL",
                        re.IGNORECASE)


def _rgmii_bus_key(net_name: str) -> str:
    """Strip RGMII signal names to get a bus prefix (e.g. 'PHY0_TXD0' → 'PHY0')."""
    cleaned = re.sub(
        r"[_\-]?(?:TXD[0-3]|RXD[0-3]|TX_?CLK|RX_?CLK|TX_?CTL|RX_?CTL|TXEN|RXDV)",
        "",
        net_name,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[^A-Z0-9]", "", cleaned.upper())


@register(
    "RGMII: verify bus completeness (TXD0-3, TX_CLK, TX_CTL, RXD0-3, RX_CLK, RX_CTL)",
    category="RGMII",
)
def rgmii_bus_completeness(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    rgmii_nets = _nets_matching(netlist, _RGMII_RE.pattern)
    if not rgmii_nets:
        return findings

    # Group by bus key
    bus_signals: Dict[str, Dict[str, str]] = defaultdict(dict)
    for net in rgmii_nets:
        key = _rgmii_bus_key(net)
        upper = net.upper().replace("_", "")
        for sig in _RGMII_TX_SIGNALS + _RGMII_RX_SIGNALS:
            if sig.replace("_", "") in upper:
                bus_signals[key][sig.replace("_", "")] = net
                break

    for bus_key, found_signals in bus_signals.items():
        # Check TX data lines
        for i in range(4):
            sig = f"TXD{i}"
            if sig not in found_signals:
                findings.append(Finding(
                    id=f"rgmii_missing_{bus_key}_{sig}",
                    check_name="rgmii_bus_completeness",
                    severity=Severity.WARN,
                    message=(
                        f"RGMII bus '{bus_key or 'default'}' is missing signal {sig}"
                    ),
                    affected=list(found_signals.values()),
                ))
        # Check RX data lines
        for i in range(4):
            sig = f"RXD{i}"
            if sig not in found_signals:
                findings.append(Finding(
                    id=f"rgmii_missing_{bus_key}_{sig}",
                    check_name="rgmii_bus_completeness",
                    severity=Severity.WARN,
                    message=(
                        f"RGMII bus '{bus_key or 'default'}' is missing signal {sig}"
                    ),
                    affected=list(found_signals.values()),
                ))
        # Check clocks and control
        for sig in ("TXCLK", "RXCLK", "TXCTL", "RXCTL"):
            alt = {"TXCLK": "TXCLK", "RXCLK": "RXCLK",
                   "TXCTL": "TXEN", "RXCTL": "RXDV"}.get(sig, sig)
            if sig not in found_signals and alt not in found_signals:
                findings.append(Finding(
                    id=f"rgmii_missing_{bus_key}_{sig}",
                    check_name="rgmii_bus_completeness",
                    severity=Severity.WARN,
                    message=(
                        f"RGMII bus '{bus_key or 'default'}' is missing "
                        f"signal {sig} / {alt}"
                    ),
                    affected=list(found_signals.values()),
                ))

    return findings


@register(
    "RGMII: check series termination resistors on data/clock lines",
    category="RGMII",
)
def rgmii_series_termination(netlist: Netlist) -> List[Finding]:
    """
    Each RGMII data and clock line should have a series resistor (typically
    33–50 Ω) close to the driver.  Flag lines with no series resistor at all.
    """
    findings: List[Finding] = []

    rgmii_nets = _nets_matching(netlist, _RGMII_RE.pattern)
    if not rgmii_nets:
        return findings

    for net in rgmii_nets:
        if not _resistors_on_net(net, netlist):
            findings.append(Finding(
                id=f"rgmii_no_series_term_{net}",
                check_name="rgmii_series_termination",
                severity=Severity.WARN,
                message=(
                    f"RGMII net '{net}' has no series resistor — "
                    f"add a 33–50 Ω damping resistor to reduce reflections"
                ),
                affected=[net],
            ))

    return findings


@register(
    "RGMII: detect voltage domain mismatch between MAC and PHY on the same RGMII bus",
    category="RGMII",
)
def rgmii_voltage_domain(netlist: Netlist) -> List[Finding]:
    """
    If any two components share an RGMII net but their other power pins
    are on different supply rails, warn of a potential level-shift issue.
    """
    findings: List[Finding] = []

    rgmii_nets = _nets_matching(netlist, _RGMII_RE.pattern)
    if not rgmii_nets:
        return findings

    def _pwr_rails_of(refdes: str) -> Set[str]:
        comp = netlist.components.get(refdes)
        if not comp:
            return set()
        return {
            p.net for p in comp.pins
            if p.net and _is_power_net(p.net)
        }

    for net_name in rgmii_nets:
        net = netlist.nets.get(net_name)
        if not net:
            continue
        comps_on_net = list({p.component for p in net.pins})
        if len(comps_on_net) < 2:
            continue

        rails_per_comp: Dict[str, Set[str]] = {
            c: _pwr_rails_of(c) for c in comps_on_net
        }

        # Compare all pairs
        for i, ca in enumerate(comps_on_net):
            for cb in comps_on_net[i + 1:]:
                ra = rails_per_comp[ca]
                rb = rails_per_comp[cb]
                if not ra or not rb:
                    continue
                # If the rail sets are disjoint (no shared supply), flag it
                if not (ra & rb):
                    findings.append(Finding(
                        id=f"rgmii_voltage_domain_{net_name}_{ca}_{cb}",
                        check_name="rgmii_voltage_domain",
                        severity=Severity.WARN,
                        message=(
                            f"RGMII net '{net_name}': {ca} ({', '.join(sorted(ra))}) "
                            f"and {cb} ({', '.join(sorted(rb))}) are on different "
                            f"supply domains — verify level compatibility or add level shifter"
                        ),
                        affected=[ca, cb],
                    ))

    return findings


# ---------------------------------------------------------------------------
# 3. MDI & physical layer
# ---------------------------------------------------------------------------

_MDI_RE = re.compile(r"MDI|(?:^|_)(?:TD|RD)[+\-]|ETHERNET_PAIR|ETH_MDI", re.IGNORECASE)
_MDI_PAIR_P = re.compile(r"[_\-]?P$|\+$|_POS$|(?:TD|RD)[+]", re.IGNORECASE)
_MDI_PAIR_N = re.compile(r"[_\-]?N$|-$|_NEG$|(?:TD|RD)[-]", re.IGNORECASE)


@register(
    "MDI: verify Bob Smith (center-tap) termination on Ethernet MDI pairs",
    category="MDI",
)
def mdi_bob_smith_termination(netlist: Netlist) -> List[Finding]:
    """
    10/100/1000BASE-T MDI pairs require a center-tap termination to chassis
    ground (or common-mode choke + cap), known as the Bob Smith termination.
    Heuristic: each MDI net should have a capacitor whose other pin connects
    to a chassis-ground or low-impedance node.
    """
    findings: List[Finding] = []

    mdi_nets = _nets_matching(netlist, _MDI_RE.pattern)
    if not mdi_nets:
        return findings

    chassis_gnd_nets: Set[str] = {
        n for n in netlist.nets
        if re.search(r"CHASSIS|SHIELD|EARTH|FRAME|PE|CGND|AGND", n, re.IGNORECASE)
    }
    any_gnd_nets: Set[str] = {n for n in netlist.nets if _is_ground_net(n)}
    reference_nets = chassis_gnd_nets if chassis_gnd_nets else any_gnd_nets

    for net_name in mdi_nets:
        caps = _caps_on_net(net_name, netlist)
        has_ct_cap = False
        for c_ref in caps:
            comp = netlist.components.get(c_ref)
            if not comp:
                continue
            other_nets = {p.net for p in comp.pins if p.net and p.net != net_name}
            if other_nets & reference_nets:
                has_ct_cap = True
                break
        if not has_ct_cap:
            findings.append(Finding(
                id=f"mdi_no_bob_smith_{net_name}",
                check_name="mdi_bob_smith_termination",
                severity=Severity.WARN,
                message=(
                    f"MDI net '{net_name}' has no center-tap capacitor to chassis/GND — "
                    f"Bob Smith termination may be missing"
                ),
                affected=[net_name],
            ))

    return findings


@register(
    "MDI: verify each MDI pair has both + and − sides defined",
    category="MDI",
)
def mdi_pair_association(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    mdi_nets = _nets_matching(netlist, _MDI_RE.pattern)
    if not mdi_nets:
        return findings

    bases_p: Dict[str, str] = {}
    bases_n: Dict[str, str] = {}

    for net in mdi_nets:
        base, side = _diff_base(net, _MDI_PAIR_P, _MDI_PAIR_N)
        if base is None:
            continue
        if side == "P":
            bases_p[base] = net
        else:
            bases_n[base] = net

    all_bases = set(bases_p) | set(bases_n)
    for base in sorted(all_bases):
        if base in bases_p and base not in bases_n:
            findings.append(Finding(
                id=f"mdi_missing_n_{base}",
                check_name="mdi_pair_association",
                severity=Severity.ERROR,
                message=(
                    f"MDI pair '{base}': + net '{bases_p[base]}' has no − counterpart"
                ),
                affected=[bases_p[base]],
            ))
        elif base in bases_n and base not in bases_p:
            findings.append(Finding(
                id=f"mdi_missing_p_{base}",
                check_name="mdi_pair_association",
                severity=Severity.ERROR,
                message=(
                    f"MDI pair '{base}': − net '{bases_n[base]}' has no + counterpart"
                ),
                affected=[bases_n[base]],
            ))

    return findings


@register(
    "MDI: check LED current-limiting resistors on Ethernet status LEDs",
    category="MDI",
)
def ethernet_led_current(netlist: Netlist) -> List[Finding]:
    """
    PHY status LEDs (LINK, SPEED, ACT) must have current-limiting resistors.
    Flag any LED component (D-prefix with LED in part number) connected to a
    net that also connects to a PHY pin but has no resistor in series.
    """
    findings: List[Finding] = []

    led_re = re.compile(r"LED|LINK|ACT|SPEED", re.IGNORECASE)
    phy_re = re.compile(r"PHY|ETHERNET|ETH", re.IGNORECASE)

    for refdes, comp in netlist.components.items():
        # Look for LED components
        if not refdes.upper().startswith("D"):
            continue
        if not led_re.search(comp.part_number or ""):
            # Relax: if it's a diode-prefix component on a LED-named net
            led_nets = [
                p.net for p in comp.pins if p.net and led_re.search(p.net)
            ]
            if not led_nets:
                continue

        for pin in comp.pins:
            if not pin.net or _is_power_net(pin.net) or _is_ground_net(pin.net):
                continue
            net = netlist.nets.get(pin.net)
            if not net:
                continue
            # Is any component on this net a PHY?
            phy_comps = [
                p.component for p in net.pins
                if phy_re.search(
                    netlist.components.get(p.component, None) and
                    (netlist.components[p.component].part_number or "") or ""
                )
            ]
            if not phy_comps:
                continue
            # Is there a resistor between LED and PHY?
            if not _resistors_on_net(pin.net, netlist):
                findings.append(Finding(
                    id=f"eth_led_no_resistor_{refdes}_{pin.net}",
                    check_name="ethernet_led_current",
                    severity=Severity.WARN,
                    message=(
                        f"LED {refdes} on net '{pin.net}' has no current-limiting "
                        f"resistor — PHY pin may be overloaded"
                    ),
                    affected=[refdes] + phy_comps,
                    sheet=comp.sheet,
                ))

    return findings


# ---------------------------------------------------------------------------
# 4. Management: MDIO / PHY control
# ---------------------------------------------------------------------------

_MDIO_RE = re.compile(r"MDIO|MDC(?!\w)", re.IGNORECASE)
_PHY_RESET_RE = re.compile(r"PHY_?RST|PHY_?RESET|ETH_?RST", re.IGNORECASE)
_PHYADDR_RE = re.compile(r"PHY_?ADDR|PHYAD", re.IGNORECASE)


@register(
    "MDIO: verify pull-up resistors on MDIO and MDC lines",
    category="MDIO",
)
def mdio_pullup(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    mdio_nets = _nets_matching(netlist, _MDIO_RE.pattern)
    if not mdio_nets:
        return findings

    for net_name in mdio_nets:
        if not _has_resistor_to_power_local(net_name, netlist):
            # MDC doesn't strictly need a pull-up (it's driven) but MDIO does
            sev = Severity.ERROR if "MDIO" in net_name.upper() else Severity.WARN
            findings.append(Finding(
                id=f"mdio_no_pullup_{net_name}",
                check_name="mdio_pullup",
                severity=sev,
                message=(
                    f"MDIO/MDC net '{net_name}' has no pull-up resistor to a "
                    f"supply rail — MDIO requires pull-up for idle state"
                ),
                affected=[net_name],
            ))

    return findings


def _has_resistor_to_power_local(net_name: str, netlist: Netlist) -> bool:
    pwr_nets: Set[str] = {n for n in netlist.nets if _is_power_net(n)}
    for refdes, comp in netlist.components.items():
        if not refdes.upper().startswith("R"):
            continue
        comp_nets = {p.net for p in comp.pins if p.net}
        if net_name in comp_nets and comp_nets & pwr_nets:
            return True
    return False


@register(
    "MDIO: detect duplicate PHY address strapping on same management bus",
    category="MDIO",
)
def phy_address_conflict(netlist: Netlist) -> List[Finding]:
    """
    PHY address pins (PHYAD[0:4] or PHY_ADDR) are strapped via resistors to
    GND or VDD.  If two PHYs share the same MDIO bus and have the same address
    strapping, management frames will collide.

    Heuristic: collect components with PHYAD/PHY_ADDR pins, determine their
    strap value (0 if net is GND, 1 if net is power, ? otherwise), and flag
    duplicates.
    """
    findings: List[Finding] = []

    addr_pin_re = re.compile(r"PHYAD\d?|PHY_?ADDR\d?|PHYADD\d?", re.IGNORECASE)

    # refdes → list of (pin_name, net) for address pins
    phy_addrs: Dict[str, List[Tuple[str, str]]] = {}
    for refdes, comp in netlist.components.items():
        addr_pins = [
            (p.name, p.net or "")
            for p in comp.pins
            if addr_pin_re.search(p.name or "")
        ]
        if addr_pins:
            phy_addrs[refdes] = addr_pins

    if len(phy_addrs) < 2:
        return findings

    def _strap_value(net: str) -> str:
        if not net:
            return "?"
        if _is_ground_net(net):
            return "0"
        if _is_power_net(net):
            return "1"
        return "?"

    # Compute address signatures
    addr_signatures: Dict[str, str] = {}
    for refdes, pins in phy_addrs.items():
        # Sort by pin name for consistent ordering
        bits = "".join(
            _strap_value(net)
            for _, net in sorted(pins, key=lambda x: x[0])
        )
        addr_signatures[refdes] = bits

    # Group by signature
    sig_groups: Dict[str, List[str]] = defaultdict(list)
    for refdes, sig in addr_signatures.items():
        if "?" not in sig:  # only flag fully-deterministic addresses
            sig_groups[sig].append(refdes)

    for sig, refs in sig_groups.items():
        if len(refs) > 1:
            findings.append(Finding(
                id=f"phy_addr_conflict_{sig}",
                check_name="phy_address_conflict",
                severity=Severity.ERROR,
                message=(
                    f"PHY address conflict: {', '.join(sorted(refs))} all have "
                    f"address strapping '{sig}' — MDIO collisions will occur"
                ),
                affected=sorted(refs),
            ))

    return findings


@register(
    "MDIO: flag PHY reset pins hard-wired to VCC (reset never asserted)",
    category="MDIO",
)
def phy_reset_sequencing(netlist: Netlist) -> List[Finding]:
    """
    PHY_RESET_N / PHY_RST should be driven by a GPIO or dedicated power
    sequencer, not tied directly to VCC (which prevents any reset assertion).
    """
    findings: List[Finding] = []

    reset_nets = _nets_matching(netlist, _PHY_RESET_RE.pattern)
    if not reset_nets:
        return findings

    for net_name in reset_nets:
        if _is_power_net(net_name):
            # Net itself is a power rail — this is a hard-wired tie to VCC
            net_obj = netlist.nets.get(net_name)
            affected_comps: List[str] = []
            if net_obj:
                affected_comps = list({p.component for p in net_obj.pins})
            findings.append(Finding(
                id=f"phy_reset_tied_vcc_{net_name}",
                check_name="phy_reset_sequencing",
                severity=Severity.ERROR,
                message=(
                    f"PHY reset net '{net_name}' appears to be a power net — "
                    f"reset is permanently de-asserted; connect to GPIO or power-on reset"
                ),
                affected=affected_comps,
            ))
            continue

        net_obj = netlist.nets.get(net_name)
        if not net_obj:
            continue

        # Check if the net only connects to a PWR pin or directly to VCC with no GPIO driver
        connected_nets_via_r: Set[str] = set()
        for refdes, comp in netlist.components.items():
            if not refdes.upper().startswith("R"):
                continue
            comp_nets = {p.net for p in comp.pins if p.net}
            if net_name in comp_nets:
                connected_nets_via_r |= comp_nets - {net_name}

        pull_to_pwr = any(_is_power_net(n) for n in connected_nets_via_r)
        has_driver = any(
            p.direction in (PinDirection.OUT, PinDirection.BIDIR, PinDirection.OC)
            for p in net_obj.pins
        )

        if pull_to_pwr and not has_driver:
            findings.append(Finding(
                id=f"phy_reset_no_driver_{net_name}",
                check_name="phy_reset_sequencing",
                severity=Severity.WARN,
                message=(
                    f"PHY reset net '{net_name}' has a pull-up but no GPIO/OC driver — "
                    f"verify reset is asserted during power-on sequence"
                ),
                affected=[net_name],
            ))

    return findings


# ---------------------------------------------------------------------------
# 5. Power & grounding
# ---------------------------------------------------------------------------

@register(
    "Power: detect direct connections between AGND and DGND (should be isolated except at star point)",
    category="PWR",
)
def agnd_dgnd_isolation(netlist: Netlist) -> List[Finding]:
    """
    AGND and DGND should be kept separate and joined at a single star point
    (often through a ferrite bead or 0 Ω link).  Direct resistive connection
    outside the designated star-point component is flagged.
    """
    findings: List[Finding] = []

    agnd_nets = {
        n for n in netlist.nets
        if re.search(r"AGND|AVSS|AGND\d", n, re.IGNORECASE)
    }
    dgnd_nets = {
        n for n in netlist.nets
        if re.search(r"^GND\d?$|DGND|DVSS|^VSS$", n, re.IGNORECASE)
    }

    if not agnd_nets or not dgnd_nets:
        return findings

    # Find components (non-ferrite, non-designated) that bridge AGND and DGND
    ferrite_re = re.compile(r"FERRITE|BEAD|FB|^FB\d|^L\d.*BEAD", re.IGNORECASE)

    for refdes, comp in netlist.components.items():
        # Skip ferrite beads and inductors used as star-point links
        if ferrite_re.search(refdes) or ferrite_re.search(comp.part_number or ""):
            continue
        # Skip 0-ohm links (R with 0/0R/0Ω in part number)
        if refdes.upper().startswith("R") and re.search(
            r"\b0[Ω R]?\b|^0R$|^0Ω$|^0ohm$", comp.part_number or "", re.IGNORECASE
        ):
            continue

        comp_nets = {p.net for p in comp.pins if p.net}
        touches_agnd = bool(comp_nets & agnd_nets)
        touches_dgnd = bool(comp_nets & dgnd_nets)

        if touches_agnd and touches_dgnd:
            findings.append(Finding(
                id=f"agnd_dgnd_bridge_{refdes}",
                check_name="agnd_dgnd_isolation",
                severity=Severity.WARN,
                message=(
                    f"{refdes} ({comp.part_number or '?'}) directly bridges "
                    f"AGND ({', '.join(sorted(comp_nets & agnd_nets))}) and "
                    f"DGND ({', '.join(sorted(comp_nets & dgnd_nets))}) — "
                    f"use ferrite bead or star-point 0Ω link"
                ),
                affected=[refdes],
                sheet=comp.sheet,
            ))

    return findings


@register(
    "Power: check ferrite bead / power filter derating on PHY supply rails",
    category="PWR",
)
def ferrite_bead_derating(netlist: Netlist) -> List[Finding]:
    """
    Ferrite beads used on PHY power supplies (AVDD, DVDD, VDD_PHY, etc.)
    must not be undersized.  Heuristic: ferrite beads (FB prefix or part
    containing BEAD/FERRITE) that bridge two power nets are checked — if
    both sides look like positive supply rails, flag for manual current rating
    review (we cannot read the actual component value from a netlist alone,
    so this is an INFO advisory).
    """
    findings: List[Finding] = []

    ferrite_re = re.compile(r"^FB\d|FERRITE|BEAD", re.IGNORECASE)

    for refdes, comp in netlist.components.items():
        if not (ferrite_re.search(refdes) or ferrite_re.search(comp.part_number or "")):
            continue

        power_nets_here = {
            p.net for p in comp.pins
            if p.net and _is_power_net(p.net)
        }
        gnd_nets_here = {
            p.net for p in comp.pins
            if p.net and _is_ground_net(p.net)
        }

        if len(power_nets_here) >= 2:
            # Ferrite between two supply rails — could be a supply filter
            findings.append(Finding(
                id=f"ferrite_derating_{refdes}",
                check_name="ferrite_bead_derating",
                severity=Severity.INFO,
                message=(
                    f"{refdes} ({comp.part_number or '?'}) is a ferrite bead between "
                    f"supply nets {', '.join(sorted(power_nets_here))} — "
                    f"verify current rating exceeds peak PHY supply current (typically >500 mA)"
                ),
                affected=[refdes],
                sheet=comp.sheet,
            ))
        elif len(power_nets_here) == 1 and gnd_nets_here:
            # Ferrite from supply to GND — unusual, flag it
            findings.append(Finding(
                id=f"ferrite_to_gnd_{refdes}",
                check_name="ferrite_bead_derating",
                severity=Severity.WARN,
                message=(
                    f"{refdes} ({comp.part_number or '?'}) is a ferrite bead between "
                    f"supply net {', '.join(power_nets_here)} and GND — "
                    f"verify this is intentional (EMI filter) and not a placement error"
                ),
                affected=[refdes],
                sheet=comp.sheet,
            ))

    return findings
