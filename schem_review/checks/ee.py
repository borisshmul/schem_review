"""EE convention checks.

All checks are registered via @register and auto-discovered when this
module is imported.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from schem_review.checks.registry import register
from schem_review.model import Finding, Netlist, Severity

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
