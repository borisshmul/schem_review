"""EE convention checks.

All checks are registered via @register and auto-discovered when this
module is imported.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from schem_review.checks.registry import register
from schem_review.model import ComponentType, Finding, Netlist, PinDirection, Severity

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_GND_TOKENS = {"GND", "VSS", "GROUND", "AGND", "DGND", "PGND"}


def _is_ground_net(name: str) -> bool:
    u = name.upper().replace("_", "").replace("-", "")
    return u in _GND_TOKENS or any(u.startswith(g) for g in _GND_TOKENS)


def _is_power_net(name: str) -> bool:
    if _is_ground_net(name):
        return False
    u = name.upper().replace("_", "")
    return any(t in u for t in ["VCC", "VDD", "VEE", "POWER", "PWR", "+3V", "+5V",
                                  "+12V", "V3", "V5", "V12", "VBAT", "VREF"])


def _nets_containing(netlist: Netlist, pattern: str, flags: int = re.IGNORECASE) -> List[str]:
    rx = re.compile(pattern, flags)
    return [n for n in netlist.nets if rx.search(n)]


def _bus_key_strip(net_name: str, signal_pattern: str) -> str:
    """Remove the signal portion from a net name to get a bus key."""
    result = re.sub(signal_pattern, "", net_name, flags=re.IGNORECASE)
    return re.sub(r"[^A-Z0-9]", "", result.upper())


def _has_resistor_to_power(net_name: str, netlist: Netlist) -> bool:
    """Return True if a resistor has one pin on net_name and another on a power net."""
    power_nets: Set[str] = {n for n in netlist.nets if _is_power_net(n)}
    for refdes, comp in netlist.components.items():
        if not refdes.upper().startswith("R"):
            continue
        comp_nets = {p.net for p in comp.pins if p.net}
        if net_name in comp_nets and comp_nets & power_nets:
            return True
    return False


def _has_resistor_to_ground(net_name: str, netlist: Netlist) -> bool:
    ground_nets: Set[str] = {n for n in netlist.nets if _is_ground_net(n)}
    for refdes, comp in netlist.components.items():
        if not refdes.upper().startswith("R"):
            continue
        comp_nets = {p.net for p in comp.pins if p.net}
        if net_name in comp_nets and comp_nets & ground_nets:
            return True
    return False


# ---------------------------------------------------------------------------
# 1. I2C
# ---------------------------------------------------------------------------

@register(
    "Check I2C SDA/SCL pairing and pull-up resistors",
    category="EE",
)
def i2c_signals(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    sda_nets = _nets_containing(netlist, r"(?<![A-Z])SDA(?![A-Z])")
    scl_nets = _nets_containing(netlist, r"(?<![A-Z])SCL(?![A-Z])")

    if not sda_nets and not scl_nets:
        return findings

    # Pair by bus key (net name with 'SDA'/'SCL' stripped)
    sda_keys: Dict[str, str] = {_bus_key_strip(n, r"SDA"): n for n in sda_nets}
    scl_keys: Dict[str, str] = {_bus_key_strip(n, r"SCL"): n for n in scl_nets}

    for key, sda in sda_keys.items():
        if key not in scl_keys:
            findings.append(Finding(
                id=f"i2c_missing_scl_{key or 'default'}",
                check_name="i2c_signals",
                severity=Severity.WARN,
                message=f"I2C net '{sda}' has no matching SCL net",
                affected=[sda],
            ))

    for key, scl in scl_keys.items():
        if key not in sda_keys:
            findings.append(Finding(
                id=f"i2c_missing_sda_{key or 'default'}",
                check_name="i2c_signals",
                severity=Severity.WARN,
                message=f"I2C net '{scl}' has no matching SDA net",
                affected=[scl],
            ))

    # Check pull-up resistors on SDA and SCL
    for net_name in sda_nets + scl_nets:
        if not _has_resistor_to_power(net_name, netlist):
            findings.append(Finding(
                id=f"i2c_no_pullup_{net_name}",
                check_name="i2c_signals",
                severity=Severity.WARN,
                message=f"I2C net '{net_name}' has no pull-up resistor to a power net",
                affected=[net_name],
            ))

    return findings


# ---------------------------------------------------------------------------
# 2. UART
# ---------------------------------------------------------------------------

@register(
    "Check UART TX/RX pairing and detect crossed connections",
    category="EE",
)
def uart_signals(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    tx_nets = _nets_containing(netlist, r"(?<![A-Z])TX(?![A-Z])|_TX$|^TX_|_TX_")
    rx_nets = _nets_containing(netlist, r"(?<![A-Z])RX(?![A-Z])|_RX$|^RX_|_RX_")

    if not tx_nets and not rx_nets:
        return findings

    tx_keys: Dict[str, str] = {_bus_key_strip(n, r"TX"): n for n in tx_nets}
    rx_keys: Dict[str, str] = {_bus_key_strip(n, r"RX"): n for n in rx_nets}

    for key, tx in tx_keys.items():
        if key not in rx_keys:
            findings.append(Finding(
                id=f"uart_missing_rx_{key or 'default'}",
                check_name="uart_signals",
                severity=Severity.WARN,
                message=f"UART net '{tx}' has no matching RX net",
                affected=[tx],
            ))

    for key, rx in rx_keys.items():
        if key not in tx_keys:
            findings.append(Finding(
                id=f"uart_missing_tx_{key or 'default'}",
                check_name="uart_signals",
                severity=Severity.WARN,
                message=f"UART net '{rx}' has no matching TX net",
                affected=[rx],
            ))

    # Heuristic: if a TX net's only connections are to pins named TX (not RX),
    # the connection may not be crossed correctly
    for tx_name in tx_nets:
        tx_net = netlist.nets.get(tx_name)
        if tx_net is None:
            continue
        pin_names = [p.name.upper() for p in tx_net.pins]
        if pin_names and all("TX" in pn and "RX" not in pn for pn in pin_names):
            findings.append(Finding(
                id=f"uart_crossed_{tx_name}",
                check_name="uart_signals",
                severity=Severity.WARN,
                message=(
                    f"UART TX net '{tx_name}' connects only to TX-named pins — "
                    f"verify TX→RX crossing"
                ),
                affected=[tx_name],
            ))

    return findings


# ---------------------------------------------------------------------------
# 3. SPI
# ---------------------------------------------------------------------------

_SPI_SIGNALS = {
    "MOSI": re.compile(r"MOSI", re.IGNORECASE),
    "MISO": re.compile(r"MISO", re.IGNORECASE),
    "SCK":  re.compile(r"(?<![A-Z])SCK(?![A-Z])|(?<![A-Z])SCLK(?![A-Z])", re.IGNORECASE),
    "CS":   re.compile(r"(?<![A-Z])(?:CS|NSS|SS|CSN|NCS)(?![A-Z])|_CS$|_NSS$|_SS$|_CS_",
                       re.IGNORECASE),
}


@register(
    "Check SPI bus signal completeness (MOSI, MISO, SCK, CS)",
    category="EE",
)
def spi_signals(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    # Gather nets per signal type
    per_signal: Dict[str, List[str]] = {sig: [] for sig in _SPI_SIGNALS}
    for net_name in netlist.nets:
        for sig, rx in _SPI_SIGNALS.items():
            if rx.search(net_name):
                per_signal[sig].append(net_name)

    if not any(per_signal.values()):
        return findings

    # Group by bus key (net name with signal stripped)
    bus_groups: Dict[str, Dict[str, List[str]]] = {}
    for sig, nets in per_signal.items():
        for net_name in nets:
            key = _bus_key_strip(net_name, _SPI_SIGNALS[sig].pattern)
            bus_groups.setdefault(key, {}).setdefault(sig, []).append(net_name)

    for key, signals_found in bus_groups.items():
        missing = [sig for sig in _SPI_SIGNALS if sig not in signals_found]
        if missing:
            present_nets: List[str] = [
                n for nets in signals_found.values() for n in nets
            ]
            bus_label = key or "default"
            findings.append(Finding(
                id=f"spi_incomplete_{bus_label}",
                check_name="spi_signals",
                severity=Severity.WARN,
                message=(
                    f"SPI bus '{bus_label}' is incomplete — "
                    f"missing: {', '.join(missing)}"
                ),
                affected=present_nets,
            ))

    return findings


# ---------------------------------------------------------------------------
# 4. Differential pairs
# ---------------------------------------------------------------------------

_DIFF_P_SUFFIXES = ("_P", "_POS", "+", "P")
_DIFF_N_SUFFIXES = ("_N", "_NEG", "-", "N")

_DIFF_P_RE = re.compile(r"(_P|_POS|\+)$", re.IGNORECASE)
_DIFF_N_RE = re.compile(r"(_N|_NEG|-)$", re.IGNORECASE)


def _diff_base(name: str) -> Optional[str]:
    """Return base name if net looks like one side of a diff pair, else None."""
    if _DIFF_P_RE.search(name):
        return _DIFF_P_RE.sub("", name)
    if _DIFF_N_RE.search(name):
        return _DIFF_N_RE.sub("", name)
    return None


@register(
    "Verify differential pair nets have both P and N sides present",
    category="EE",
)
def differential_pairs(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    bases_p: Dict[str, str] = {}
    bases_n: Dict[str, str] = {}

    for net_name in netlist.nets:
        if _DIFF_P_RE.search(net_name):
            base = _DIFF_P_RE.sub("", net_name)
            bases_p[base.upper()] = net_name
        elif _DIFF_N_RE.search(net_name):
            base = _DIFF_N_RE.sub("", net_name)
            bases_n[base.upper()] = net_name

    all_bases = set(bases_p) | set(bases_n)
    for base in sorted(all_bases):
        has_p = base in bases_p
        has_n = base in bases_n
        if has_p and not has_n:
            findings.append(Finding(
                id=f"diffpair_missing_n_{base}",
                check_name="differential_pairs",
                severity=Severity.WARN,
                message=f"Differential pair '{base}' has P side ('{bases_p[base]}') but no N side",
                affected=[bases_p[base]],
            ))
        elif has_n and not has_p:
            findings.append(Finding(
                id=f"diffpair_missing_p_{base}",
                check_name="differential_pairs",
                severity=Severity.WARN,
                message=f"Differential pair '{base}' has N side ('{bases_n[base]}') but no P side",
                affected=[bases_n[base]],
            ))

    return findings


# ---------------------------------------------------------------------------
# 5. Power rail naming
# ---------------------------------------------------------------------------

_PWR_RAIL_RE = re.compile(
    r"^(VCC|VDD|VEE|VBAT|VREF|V[0-9]|[+\-][0-9])|"
    r"(VCC|VDD|GND|VSS|PWR|POWER)$",
    re.IGNORECASE,
)


@register(
    "Flag power nets that don't follow the dominant naming convention in the design",
    category="EE",
)
def power_rail_naming(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    power_nets = [n for n in netlist.nets if _PWR_RAIL_RE.search(n)]
    if len(power_nets) < 3:
        return findings  # not enough data for convention detection

    # Classify: VCC-style vs VDD-style
    vcc_style = [n for n in power_nets if "VCC" in n.upper()]
    vdd_style = [n for n in power_nets if "VDD" in n.upper()]

    dominant: Optional[str] = None
    minority: List[str] = []
    if len(vcc_style) > len(vdd_style) and vdd_style:
        dominant = "VCC"
        minority = vdd_style
    elif len(vdd_style) > len(vcc_style) and vcc_style:
        dominant = "VDD"
        minority = vcc_style

    if dominant and minority:
        findings.append(Finding(
            id="power_rail_convention",
            check_name="power_rail_naming",
            severity=Severity.WARN,
            message=(
                f"Mixed power rail style: design uses mostly '{dominant}' convention "
                f"but also has: {', '.join(sorted(minority))}"
            ),
            affected=sorted(minority),
        ))

    return findings


# ---------------------------------------------------------------------------
# 6. Reset signals
# ---------------------------------------------------------------------------

_RESET_RE = re.compile(r"\bRST\b|RESET|NRST", re.IGNORECASE)
_ACTIVE_LOW_RESET_RE = re.compile(
    r"^N_?RST|^NRST|RST_?N$|RST_?B$|RST#$|/RST", re.IGNORECASE
)
_ACTIVE_HIGH_RESET_RE = re.compile(r"^RST(?!N|_N|B|_B|#)|_RST$", re.IGNORECASE)


@register(
    "Check reset signal naming for active-low convention consistency",
    category="EE",
)
def reset_signals(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    rst_nets = [n for n in netlist.nets if _RESET_RE.search(n)]
    if not rst_nets:
        return findings

    active_low = [n for n in rst_nets if _ACTIVE_LOW_RESET_RE.search(n)]
    active_high = [n for n in rst_nets if not _ACTIVE_LOW_RESET_RE.search(n)]

    # If both naming styles coexist, flag inconsistency
    if active_low and active_high:
        findings.append(Finding(
            id="reset_naming_inconsistency",
            check_name="reset_signals",
            severity=Severity.WARN,
            message=(
                f"Inconsistent reset naming: active-low style ({', '.join(sorted(active_low))}) "
                f"mixed with likely active-high style ({', '.join(sorted(active_high))})"
            ),
            affected=sorted(rst_nets),
        ))

    # Flag resets that look active-low by name but don't have conventional suffix
    for net in rst_nets:
        u = net.upper()
        if "NRST" in u or "RST_N" in u or "RST_B" in u:
            continue  # clearly marked active-low
        if "RESET" in u and not _ACTIVE_LOW_RESET_RE.search(net):
            findings.append(Finding(
                id=f"reset_ambiguous_{net}",
                check_name="reset_signals",
                severity=Severity.INFO,
                message=(
                    f"Reset net '{net}' — active polarity is ambiguous; "
                    f"consider naming with N-prefix or #/B-suffix for active-low"
                ),
                affected=[net],
            ))

    return findings


# ---------------------------------------------------------------------------
# 7. Enable signals
# ---------------------------------------------------------------------------

_EN_RE = re.compile(r"(?<![A-Z])(?:EN|OE)(?![A-Z])|_EN$|_OE$|^EN_|^OE_|_EN_|_OE_",
                    re.IGNORECASE)
_EN_HASH = re.compile(r"#$|_N$|^N_|^N(?=[A-Z])", re.IGNORECASE)


@register(
    "Flag inconsistent active-low naming for enable/output-enable signals",
    category="EE",
)
def enable_signals(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    en_nets = [n for n in netlist.nets if _EN_RE.search(n)]
    if len(en_nets) < 2:
        return findings

    # Classify: hash-style (EN#, OE#) vs N-prefix (N_EN, NOE)
    hash_style = [n for n in en_nets if re.search(r"#$|_N$|_B$", n)]
    n_prefix_style = [n for n in en_nets if re.search(r"^N_|^N(?=[A-Z])|^/", n)]

    if hash_style and n_prefix_style:
        findings.append(Finding(
            id="enable_naming_inconsistency",
            check_name="enable_signals",
            severity=Severity.WARN,
            message=(
                f"Inconsistent active-low enable naming: "
                f"suffix style ({', '.join(sorted(hash_style))}) mixed with "
                f"prefix style ({', '.join(sorted(n_prefix_style))})"
            ),
            affected=sorted(hash_style + n_prefix_style),
        ))

    return findings


# ---------------------------------------------------------------------------
# 8. Clock signals
# ---------------------------------------------------------------------------

_CLK_RE = re.compile(r"CLK|CLOCK", re.IGNORECASE)


@register(
    "Check clock signals: flag differential clocks missing their pair",
    category="EE",
)
def clock_signals(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    clk_nets = [n for n in netlist.nets if _CLK_RE.search(n)]
    if not clk_nets:
        return findings

    _DIFF_P = re.compile(r"(_P|_POS|\+)$", re.IGNORECASE)
    _DIFF_N = re.compile(r"(_N|_NEG|-)$", re.IGNORECASE)

    diff_p: Dict[str, str] = {}
    diff_n: Dict[str, str] = {}

    for net in clk_nets:
        if _DIFF_P.search(net):
            base = _DIFF_P.sub("", net).upper()
            diff_p[base] = net
        elif _DIFF_N.search(net):
            base = _DIFF_N.sub("", net).upper()
            diff_n[base] = net

    all_bases = set(diff_p) | set(diff_n)
    for base in sorted(all_bases):
        if base in diff_p and base not in diff_n:
            findings.append(Finding(
                id=f"clk_missing_n_{base}",
                check_name="clock_signals",
                severity=Severity.WARN,
                message=(
                    f"Differential clock '{diff_p[base]}' has P side but no N side"
                ),
                affected=[diff_p[base]],
            ))
        elif base in diff_n and base not in diff_p:
            findings.append(Finding(
                id=f"clk_missing_p_{base}",
                check_name="clock_signals",
                severity=Severity.WARN,
                message=(
                    f"Differential clock '{diff_n[base]}' has N side but no P side"
                ),
                affected=[diff_n[base]],
            ))

    return findings


# ---------------------------------------------------------------------------
# 9. JTAG / SWD signals
# ---------------------------------------------------------------------------

# Required signals for each debug interface.
# Each entry: signal key -> regex that matches nets belonging to that signal.
_JTAG_SIGNALS: Dict[str, re.Pattern] = {
    "TDI":  re.compile(r"(?<![A-Z])TDI(?![A-Z])|_TDI$|^TDI_", re.IGNORECASE),
    "TDO":  re.compile(r"(?<![A-Z])TDO(?![A-Z])|_TDO$|^TDO_", re.IGNORECASE),
    "TMS":  re.compile(r"(?<![A-Z])TMS(?![A-Z])|_TMS$|^TMS_", re.IGNORECASE),
    "TCK":  re.compile(r"(?<![A-Z])TCK(?![A-Z])|_TCK$|^TCK_|JTAG_CLK", re.IGNORECASE),
}

_SWD_SIGNALS: Dict[str, re.Pattern] = {
    "SWDIO": re.compile(r"SWDIO|SWD_IO|SWD_DATA", re.IGNORECASE),
    "SWDCLK": re.compile(r"SWDCLK|SWD_CLK|SWCLK", re.IGNORECASE),
}

# SWO is optional (trace output) — flag as INFO if SWD is present but SWO is absent
_SWO_RE = re.compile(r"(?<![A-Z])SWO(?![A-Z])|SWD_SWO|TRACESWO", re.IGNORECASE)
# NRST is strongly recommended alongside SWD
_NRST_RE = re.compile(r"NRST|N_RST|RST_N|RESET_N|/RESET", re.IGNORECASE)


@register(
    "Check JTAG (TDI/TDO/TMS/TCK) and SWD (SWDIO/SWDCLK) debug interface completeness",
    category="EE",
)
def jtag_swd_signals(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []
    net_names = list(netlist.nets.keys())

    # Detect which interfaces are present
    jtag_found: Dict[str, List[str]] = {}
    for sig, rx in _JTAG_SIGNALS.items():
        matches = [n for n in net_names if rx.search(n)]
        if matches:
            jtag_found[sig] = matches

    swd_found: Dict[str, List[str]] = {}
    for sig, rx in _SWD_SIGNALS.items():
        matches = [n for n in net_names if rx.search(n)]
        if matches:
            swd_found[sig] = matches

    has_jtag = bool(jtag_found)
    has_swd = bool(swd_found)

    if not has_jtag and not has_swd:
        return findings  # no debug interface detected — don't flag

    # ---- JTAG completeness ------------------------------------------------
    if has_jtag:
        missing_jtag = [sig for sig in _JTAG_SIGNALS if sig not in jtag_found]
        if missing_jtag:
            present_nets = [n for nets in jtag_found.values() for n in nets]
            findings.append(Finding(
                id="jtag_incomplete",
                check_name="jtag_swd_signals",
                severity=Severity.WARN,
                message=(
                    f"JTAG interface is incomplete — "
                    f"missing signal(s): {', '.join(missing_jtag)}"
                ),
                affected=present_nets,
            ))

    # ---- SWD completeness -------------------------------------------------
    if has_swd:
        missing_swd = [sig for sig in _SWD_SIGNALS if sig not in swd_found]
        if missing_swd:
            present_nets = [n for nets in swd_found.values() for n in nets]
            findings.append(Finding(
                id="swd_incomplete",
                check_name="jtag_swd_signals",
                severity=Severity.WARN,
                message=(
                    f"SWD interface is incomplete — "
                    f"missing signal(s): {', '.join(missing_swd)}"
                ),
                affected=present_nets,
            ))

        # SWO (trace) — informational if absent
        has_swo = any(_SWO_RE.search(n) for n in net_names)
        if not has_swo:
            present_nets = [n for nets in swd_found.values() for n in nets]
            findings.append(Finding(
                id="swd_no_swo",
                check_name="jtag_swd_signals",
                severity=Severity.INFO,
                message=(
                    "SWD interface present but no SWO/trace net found — "
                    "add SWO if printf-style trace output is needed"
                ),
                affected=present_nets,
            ))

        # NRST alongside SWD
        has_nrst = any(_NRST_RE.search(n) for n in net_names)
        if not has_nrst:
            present_nets = [n for nets in swd_found.values() for n in nets]
            findings.append(Finding(
                id="swd_no_nrst",
                check_name="jtag_swd_signals",
                severity=Severity.WARN,
                message=(
                    "SWD interface present but no NRST net found — "
                    "debugger cannot force a hardware reset without NRST"
                ),
                affected=present_nets,
            ))

    return findings


# ---------------------------------------------------------------------------
# 10. USB Full Speed D+ pull-up
# ---------------------------------------------------------------------------

_USB_DP_RE = re.compile(r'USB_?D\+?P$|DP$|D\+$|USBDP', re.IGNORECASE)
_USB_DM_RE = re.compile(r'USB_?D\-?M$|DM$|D\-$|USBDM', re.IGNORECASE)


@register(
    "USB Full Speed: verify 1.5 kΩ D+ pull-up resistor exists for host enumeration",
    category="EE",
)
def usb_dp_pullup(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    dp_nets = [n for n in netlist.nets if _USB_DP_RE.search(n)]
    if not dp_nets:
        return findings

    for dp_net in dp_nets:
        net = netlist.nets[dp_net]
        # Look for a resistor bridging D+ to a power net
        has_pullup = False
        power_nets = {n for n in netlist.nets if _is_power_net(n)}
        for refdes, comp in netlist.components.items():
            if comp.component_type != ComponentType.RESISTOR:
                continue
            comp_nets = {p.net for p in comp.pins if p.net}
            if dp_net in comp_nets and comp_nets & power_nets:
                has_pullup = True
                break

        if not has_pullup:
            findings.append(Finding(
                id=f"usb_no_dp_pullup_{dp_net}",
                check_name="usb_dp_pullup",
                severity=Severity.ERROR,
                message=(
                    f"USB D+ net '{dp_net}' has no pull-up resistor to a power rail — "
                    f"USB Full Speed device will not enumerate on the host"
                ),
                affected=[dp_net],
            ))

    return findings


# ---------------------------------------------------------------------------
# 11. Crystal load capacitors
# ---------------------------------------------------------------------------

_XTAL_PIN_RE = re.compile(
    r'^(XI|XO|XTAL\d?|OSC_?IN|OSC_?OUT|X\d?IN|X\d?OUT|EXTAL|XTAL_?[PN])$',
    re.IGNORECASE,
)


@register(
    "Crystal/oscillator: verify symmetric load capacitors on both oscillator pins",
    category="EE",
)
def crystal_load_caps(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    ground_nets = {n for n in netlist.nets if _is_ground_net(n)}

    # Find crystal components directly, or ICs with XTAL-named pins
    for refdes, comp in netlist.components.items():
        xtal_pins = [p for p in comp.pins if _XTAL_PIN_RE.match(p.name)]
        if not xtal_pins:
            continue
        if comp.component_type == ComponentType.CAPACITOR:
            continue  # skip caps themselves

        for pin in xtal_pins:
            if not pin.net:
                continue
            # Check for a cap from this pin to any ground net
            net_comps = [
                netlist.components[p.component]
                for p in (netlist.nets.get(pin.net) or _empty_net()).pins
                if p.component != refdes and p.component in netlist.components
            ]
            load_cap = any(
                c.component_type == ComponentType.CAPACITOR
                and any(
                    p2.net in ground_nets
                    for p2 in c.pins
                    if p2.net
                )
                for c in net_comps
            )
            if not load_cap:
                findings.append(Finding(
                    id=f"xtal_no_load_cap_{refdes}_{pin.name}",
                    check_name="crystal_load_caps",
                    severity=Severity.WARN,
                    message=(
                        f"{refdes} oscillator pin '{pin.name}' (net '{pin.net}') "
                        f"has no load capacitor to ground — oscillator may not start "
                        f"or will have incorrect frequency"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))

    return findings


def _empty_net():
    from schem_review.model import Net
    return Net(name="")


# ---------------------------------------------------------------------------
# 12. Differential pair — component-level check
# ---------------------------------------------------------------------------

_DIFF_PAIR_PIN_P = re.compile(r'(_P|_POS|\+)$', re.IGNORECASE)
_DIFF_PAIR_PIN_N = re.compile(r'(_N|_NEG|-)$',  re.IGNORECASE)


@register(
    "Differential pair: component pin-level check — flags when one side is absent from schematic",
    category="EE",
)
def diff_pair_component_level(netlist: Netlist) -> List[Finding]:
    """Checks each component's pin list for P/N pairs where one side is uninstantiated.

    This catches cases like a missing CLKin0_N pin on LMK04828 that the
    net-name-based differential_pairs check cannot see.
    """
    findings: List[Finding] = []

    for refdes, comp in netlist.components.items():
        # Build map: base_name_upper → {P: pin, N: pin}
        pairs: Dict[str, Dict[str, object]] = {}
        for pin in comp.pins:
            if _DIFF_PAIR_PIN_P.search(pin.name):
                base = _DIFF_PAIR_PIN_P.sub("", pin.name).upper()
                pairs.setdefault(base, {})["P"] = pin
            elif _DIFF_PAIR_PIN_N.search(pin.name):
                base = _DIFF_PAIR_PIN_N.sub("", pin.name).upper()
                pairs.setdefault(base, {})["N"] = pin

        for base, sides in pairs.items():
            p_pin = sides.get("P")
            n_pin = sides.get("N")
            if p_pin and not n_pin:
                findings.append(Finding(
                    id=f"diffpair_comp_missing_n_{refdes}_{base}",
                    check_name="diff_pair_component_level",
                    severity=Severity.ERROR,
                    message=(
                        f"{refdes} ({comp.part_number}): differential pin '{base}_P' "
                        f"is present but '{base}_N' is not instantiated in the schematic"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))
            elif n_pin and not p_pin:
                findings.append(Finding(
                    id=f"diffpair_comp_missing_p_{refdes}_{base}",
                    check_name="diff_pair_component_level",
                    severity=Severity.ERROR,
                    message=(
                        f"{refdes} ({comp.part_number}): differential pin '{base}_N' "
                        f"is present but '{base}_P' is not instantiated in the schematic"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))

    return findings


# ---------------------------------------------------------------------------
# 13. Power enable pin with no driver
# ---------------------------------------------------------------------------

_EN_PIN_RE = re.compile(
    r'^(EN|ENABLE|OE|CE|SHDN|SHUTDOWN|RUN|ON_OFF|EN\d|PD|PWR_EN)$',
    re.IGNORECASE,
)
_DRIVER_DIRS = {PinDirection.OUT, PinDirection.PWR, PinDirection.BIDIR,
                PinDirection.OC, PinDirection.TRISTATE}


@register(
    "Power enable/shutdown pin with no external driver — startup state is undefined",
    category="EE",
)
def power_enable_undriven(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    for refdes, comp in netlist.components.items():
        if comp.component_type not in (ComponentType.REGULATOR, ComponentType.IC):
            continue

        for pin in comp.pins:
            if not _EN_PIN_RE.match(pin.name):
                continue
            if not pin.net:
                # Completely unconnected enable pin
                findings.append(Finding(
                    id=f"en_unconnected_{refdes}_{pin.name}",
                    check_name="power_enable_undriven",
                    severity=Severity.WARN,
                    message=(
                        f"{refdes} ({comp.part_number}) enable pin '{pin.name}' is "
                        f"unconnected — startup state is undefined (floating enable)"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))
                continue

            net = netlist.nets.get(pin.net)
            if not net:
                continue

            # Check for a driver on this net (exclude the component itself)
            has_driver = any(
                p.direction in _DRIVER_DIRS
                for p in net.pins
                if p.component != refdes
            )
            # A pull-up or pull-down resistor to a rail is acceptable
            has_bias_r = any(
                netlist.components.get(p.component, comp).component_type
                == ComponentType.RESISTOR
                for p in net.pins
                if p.component != refdes
            )

            if not has_driver and not has_bias_r and len(net.pins) <= 1:
                findings.append(Finding(
                    id=f"en_undriven_{refdes}_{pin.name}",
                    check_name="power_enable_undriven",
                    severity=Severity.WARN,
                    message=(
                        f"{refdes} ({comp.part_number}) enable pin '{pin.name}' "
                        f"(net '{pin.net}') has no driver or bias resistor — "
                        f"startup polarity is uncontrolled"
                    ),
                    affected=[refdes],
                    sheet=comp.sheet,
                ))

    return findings


# ---------------------------------------------------------------------------
# 14. I2C address conflicts
# ---------------------------------------------------------------------------

# Known device base addresses: part_number_prefix → (base_addr_7bit, addr_pin_names)
_I2C_ADDR_DB: Dict[str, tuple] = {
    "AT24C":   (0x50, ["A0", "A1", "A2"]),
    "M24C":    (0x50, ["A0", "A1", "A2"]),
    "24LC":    (0x50, ["A0", "A1", "A2"]),
    "24AA":    (0x50, ["A0", "A1", "A2"]),
    "PCF8574": (0x20, ["A0", "A1", "A2"]),
    "MCP2301": (0x20, ["A0", "A1", "A2"]),
    "PCA9555": (0x20, ["A0", "A1", "A2"]),
    "PCA9685": (0x40, ["A0", "A1", "A2", "A3", "A4", "A5"]),
    "INA219":  (0x40, ["A0", "A1"]),
    "INA226":  (0x40, ["A0", "A1"]),
    "INA260":  (0x40, ["A0", "A1"]),
    "ADS1115": (0x48, ["ADDR"]),
    "ADS1015": (0x48, ["ADDR"]),
    "MPU6050": (0x68, ["AD0"]),
    "MPU6500": (0x68, ["AD0"]),
    "ICM4268": (0x68, ["AD0"]),
    "DS1307":  (0x68, []),
    "DS3231":  (0x68, []),
    "BMP280":  (0x76, ["SDO"]),
    "BME280":  (0x76, ["SDO"]),
    "LIS3DH":  (0x18, ["SDO", "SA0"]),
    "SSD1306": (0x3C, ["SA0"]),
}


def _i2c_addr_signature(comp, db_entry: tuple) -> int:
    """Compute 7-bit I2C address from address pin states."""
    base_addr, addr_pins = db_entry
    if not addr_pins:
        return base_addr
    bit = 0
    addr = base_addr
    for pin_name in addr_pins:
        pin = comp.pin_by_name(pin_name)
        if pin and pin.net:
            # VCC → bit=1, GND → bit=0
            if _is_power_net(pin.net):
                addr |= (1 << bit)
        bit += 1
    return addr


@register(
    "I2C: detect devices on the same bus with conflicting 7-bit addresses",
    category="EE",
)
def i2c_address_conflicts(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    sda_nets = [n for n in netlist.nets if re.search(r'(?<![A-Z])SDA(?![A-Z])', n, re.IGNORECASE)]
    scl_nets = [n for n in netlist.nets if re.search(r'(?<![A-Z])SCL(?![A-Z])', n, re.IGNORECASE)]

    if not sda_nets:
        return findings

    # Group into buses: strip "SDA"/"SCL" and match by key
    def _bus_key(net: str, sig: str) -> str:
        return re.sub(sig, "", net, flags=re.IGNORECASE).upper().strip("_- ")

    sda_buses = {_bus_key(n, "SDA"): n for n in sda_nets}

    for key, sda_net in sda_buses.items():
        # Find all ICs on this SDA bus
        bus_comps = [
            comp for comp in netlist.components.values()
            if comp.component_type in (ComponentType.IC, ComponentType.REGULATOR)
            and any(p.net == sda_net for p in comp.pins)
        ]

        # Resolve addresses for known parts
        addr_map: Dict[int, List[str]] = {}  # addr → [refdes, ...]
        for comp in bus_comps:
            pn = comp.part_number or ""
            db_entry = next(
                (entry for prefix, entry in _I2C_ADDR_DB.items()
                 if pn.upper().startswith(prefix.upper())),
                None,
            )
            if db_entry is None:
                continue
            addr = _i2c_addr_signature(comp, db_entry)
            addr_map.setdefault(addr, []).append(comp.refdes)

        for addr, refdes_list in addr_map.items():
            if len(refdes_list) > 1:
                bus_label = f"I2C bus '{sda_net}'" if key == "" else f"I2C bus '{key}'"
                findings.append(Finding(
                    id=f"i2c_addr_conflict_{key or 'default'}_{addr:#04x}",
                    check_name="i2c_address_conflicts",
                    severity=Severity.ERROR,
                    message=(
                        f"{bus_label}: address conflict at 0x{addr:02X} — "
                        f"devices {', '.join(sorted(refdes_list))} share the same address"
                    ),
                    affected=sorted(refdes_list),
                    confidence=0.75,
                ))

    return findings


# ---------------------------------------------------------------------------
# 15. I2C pull-up value vs. bus speed
# ---------------------------------------------------------------------------

# I2C spec (Table 10, UM10204): max pull-up R for each speed
_I2C_SPEED_LIMITS = [
    (50_000,  "Standard Mode (100 kHz)",  50e3),   # max 50 kΩ — but effectively 1/Cb
    (12_500,  "Fast Mode (400 kHz)",      12.5e3),
    (1_000,   "Fast-Plus Mode (1 MHz)",   1e3),
]


@register(
    "I2C: pull-up resistor value exceeds the Fast Mode (400 kHz) maximum of 12.5 kΩ",
    category="EE",
)
def i2c_pullup_speed(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    i2c_nets = [
        n for n in netlist.nets
        if re.search(r'(?<![A-Z])(SDA|SCL)(?![A-Z])', n, re.IGNORECASE)
    ]

    power_nets = {n for n in netlist.nets if _is_power_net(n)}

    for net_name in i2c_nets:
        for refdes, comp in netlist.components.items():
            if comp.component_type != ComponentType.RESISTOR:
                continue
            comp_nets = {p.net for p in comp.pins if p.net}
            if net_name not in comp_nets:
                continue
            if not (comp_nets & power_nets):
                continue  # not a pull-up (no pin on a power net)

            if comp.value is None:
                continue  # can't check without a parsed value

            # Check against Fast Mode threshold (most common I2C speed)
            if comp.value > 12.5e3:
                findings.append(Finding(
                    id=f"i2c_pullup_too_high_{refdes}_{net_name}",
                    check_name="i2c_pullup_speed",
                    severity=Severity.WARN,
                    message=(
                        f"{refdes} ({comp.value_str}) on I2C net '{net_name}' exceeds "
                        f"the Fast Mode (400 kHz) maximum of 12.5 kΩ — "
                        f"use ≤4.7 kΩ for reliable 400 kHz operation"
                    ),
                    affected=[refdes],
                    confidence=0.85,
                ))

    return findings


# ---------------------------------------------------------------------------
# 16. Test point coverage score
# ---------------------------------------------------------------------------

_DEBUG_NET_RE = re.compile(
    r'UART|USART|SDA|SCL|MOSI|MISO|SCK|SWDIO|SWDCLK|TDI|TDO|TMS|TCK|'
    r'CLK|CLOCK|STATUS|RESET|NRST|TX_|_TX|RX_|_RX|DEBUG|DIAG',
    re.IGNORECASE,
)


@register(
    "Test point coverage: flag debug/protocol nets with no associated test point",
    category="EE",
)
def test_coverage_score(netlist: Netlist) -> List[Finding]:
    findings: List[Finding] = []

    # Find all test-point nets
    tp_nets: set = set()
    for comp in netlist.components.values():
        if comp.component_type == ComponentType.TESTPOINT:
            for pin in comp.pins:
                if pin.net:
                    tp_nets.add(pin.net)

    # Find all debug/protocol signal nets
    debug_nets = [n for n in netlist.nets if _DEBUG_NET_RE.search(n)
                  and not _is_ground_net(n) and not _is_power_net(n)]

    if not debug_nets:
        return findings

    uncovered = [n for n in debug_nets if n not in tp_nets]
    covered   = [n for n in debug_nets if n in tp_nets]
    pct = len(covered) / len(debug_nets) * 100

    if uncovered:
        findings.append(Finding(
            id="test_coverage_score",
            check_name="test_coverage_score",
            severity=Severity.INFO,
            message=(
                f"Test point coverage: {len(covered)}/{len(debug_nets)} "
                f"debug/protocol nets have a test point ({pct:.0f}%). "
                f"Uncovered: {', '.join(sorted(uncovered)[:10])}"
                + (" …" if len(uncovered) > 10 else "")
            ),
            affected=sorted(uncovered),
            confidence=0.9,
        ))

    return findings
