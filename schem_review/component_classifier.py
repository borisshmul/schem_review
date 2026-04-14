"""Component value parser and type classifier.

Populates Component.value, Component.value_str, Component.package,
and Component.component_type from the component's refdes and part_number.

Called by parsers after all pins have been attached to each component,
so pin-name hints (e.g. SW pin confirming a switching regulator) are available.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from schem_review.model import Component

from schem_review.model import ComponentType

# ---------------------------------------------------------------------------
# Package detection
# ---------------------------------------------------------------------------

_PACKAGE_RE = re.compile(
    r'\b(0201|0402|0603|0805|1206|1210|1812|2010|2512'
    r'|SOT-?23(?:-\d+)?|SOT-?323|SOT-?363|SOT-?563|SOT-?723'
    r'|SOT-?89|SOT-?223|TO-?92|TO-?252|TO-?263|TO-?220'
    r'|DFN-?\d*|QFN-?\d*|QFP-?\d*|BGA-?\d*|TSSOP-?\d*'
    r'|SOIC-?\d*|SOP-?\d*|TQFP-?\d*|LQFP-?\d*'
    r'|DPAK|D2PAK|IPAK|WSON|VSON|USON|HVSON)\b',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Value detection
# ---------------------------------------------------------------------------

# SI prefix → multiplier (case-sensitive: 'm' = milli, 'M' = mega)
_PREFIX_MULT = {
    'p': 1e-12, 'P': 1e-12,
    'n': 1e-9,
    'u': 1e-6,  'U': 1e-6, 'µ': 1e-6,
    'm': 1e-3,
    'k': 1e3,   'K': 1e3,
    'M': 1e6,
    'G': 1e9,
}

# Matches SI notation: 100nF, 10uF, 4.7K, 3.3V, 1mH, 100pF
# Negative lookahead (?!\d) prevents matching "4K" inside "4K7" (European notation)
_SI_VALUE_RE = re.compile(
    r'(\d+(?:\.\d+)?)\s*'    # mantissa
    r'([pPnuUµmkKMG])'       # SI prefix
    r'([FfHhVvΩRr]?)'        # optional unit char
    r'(?!\d)',                # not followed by digit (avoids matching "4K" in "4K7")
)

# European notation: 4K7 → 4.7kΩ, 2K2 → 2.2kΩ, 4R7 → 4.7Ω, 3V3 → 3.3V, 100R → 100Ω
_EURO_RE = re.compile(r'^(\d+)([RrKkMmVv])(\d*)$')

# Plain numeric with unit suffix: 47R, 100Ω, 0R
_PLAIN_RE = re.compile(r'^(\d+(?:\.\d+)?)([RΩ])$', re.IGNORECASE)


def _extract_value(part_number: str) -> Tuple[Optional[float], str, str]:
    """Return (value_si, value_str, unit).  unit is one of Ω / F / H / V / ''.

    Returns (None, '', '') if no parseable value is found.
    """
    # 1. SI notation scan across the entire string
    for m in _SI_VALUE_RE.finditer(part_number):
        mantissa = float(m.group(1))
        prefix   = m.group(2)
        unit_ch  = m.group(3).upper() if m.group(3) else ''
        mult     = _PREFIX_MULT.get(prefix, 1.0)
        value    = mantissa * mult
        unit     = _infer_unit(unit_ch, prefix)
        return value, m.group(0).strip(), unit

    # 2. Token-by-token scan for European notation
    for token in re.split(r'[_\-\s]', part_number):
        # European: 4K7, 2K2, 4R7, 3V3, 100R
        m = _EURO_RE.match(token)
        if m:
            a, sep, b = m.group(1), m.group(2).upper(), m.group(3)
            mult_map = {'R': 1.0, 'K': 1e3, 'M': 1e6, 'V': 1.0}
            mult = mult_map.get(sep, 1.0)
            val  = (int(a) + int(b) / 10 ** len(b)) * mult if b else int(a) * mult
            unit = 'V' if sep == 'V' else 'Ω'
            return val, token, unit

        # Plain ohms: 47R, 100Ω
        m2 = _PLAIN_RE.match(token)
        if m2:
            return float(m2.group(1)), token, 'Ω'

    return None, '', ''


def _infer_unit(unit_ch: str, prefix: str) -> str:
    """Determine SI unit from the explicit unit character or the prefix context."""
    if unit_ch == 'F':
        return 'F'
    if unit_ch == 'H':
        return 'H'
    if unit_ch in ('V',):
        return 'V'
    if unit_ch in ('R', 'Ω'):
        return 'Ω'
    # No explicit unit — infer from prefix magnitude
    if prefix.lower() in ('p', 'n', 'u', 'µ', 'm'):
        return 'F'   # small prefix without unit → typically capacitance
    if prefix in ('k', 'K', 'M', 'G'):
        return 'Ω'   # large prefix without unit → typically resistance
    return ''


# ---------------------------------------------------------------------------
# Component type classification
# ---------------------------------------------------------------------------

# Refdes-prefix rules (checked first; most reliable)
_REFDES_TYPE_MAP = [
    (re.compile(r'^R\d',          re.IGNORECASE), ComponentType.RESISTOR),
    (re.compile(r'^C\d',          re.IGNORECASE), ComponentType.CAPACITOR),
    (re.compile(r'^FB\d|^L_FB\d', re.IGNORECASE), ComponentType.FERRITE),
    (re.compile(r'^L\d',          re.IGNORECASE), ComponentType.INDUCTOR),
    (re.compile(r'^D\d|^LED\d',   re.IGNORECASE), ComponentType.DIODE),   # refined below
    (re.compile(r'^U\d|^IC\d',    re.IGNORECASE), ComponentType.IC),
    (re.compile(r'^J\d|^P\d|^CN\d|^CON\d|^XP\d', re.IGNORECASE), ComponentType.CONNECTOR),
    (re.compile(r'^TP\d',         re.IGNORECASE), ComponentType.TESTPOINT),
    (re.compile(r'^F\d|^FU\d',    re.IGNORECASE), ComponentType.FUSE),
    (re.compile(r'^Q\d|^T\d',     re.IGNORECASE), ComponentType.TRANSISTOR),
    (re.compile(r'^Y\d|^X\d|^OSC\d|^XTAL\d', re.IGNORECASE), ComponentType.CRYSTAL),
    (re.compile(r'^SW\d|^S\d',    re.IGNORECASE), ComponentType.SWITCH),
]

# Part-number keyword rules (applied when refdes gives UNKNOWN or IC)
_PARTNUM_TYPE_MAP = [
    # LED — must precede generic DIODE
    (re.compile(r'\bLED\b',          re.IGNORECASE), ComponentType.LED),
    # TVS / ESD protection diodes
    (re.compile(r'TVS|PRTR|USBLC|CDSOT|ESDA|SMBJ|P6KE|P4KE|SMAJ',
                re.IGNORECASE), ComponentType.DIODE),
    # Switching regulators (TPS, LMR, LT, MAX, ADP, ISL, MP, XL, RT, NCP…)
    (re.compile(r'^TPS\d|^LMR\d|^LM\d{4}|^LT\d{4}|^MAX\d{4}|^ADP\d|'
                r'^ISL\d|^MP\d{4}|^XL\d{4}|^RT\d{4}|^NCP\d|^UCC\d|^UC\d{4}',
                re.IGNORECASE), ComponentType.REGULATOR),
    # Linear regulators
    (re.compile(r'\bLDO\b|AMS1117|AP2112|MCP1700|LP\d{4}|LD\d{4}|NCP\d{3}|'
                r'LM317|LM7[3589]|SPX\d|TLV\d{5}',
                re.IGNORECASE), ComponentType.REGULATOR),
    # Ferrite beads
    (re.compile(r'FERRITE|BEAD|BLM\d|MMZ\d|HI\d{4}', re.IGNORECASE), ComponentType.FERRITE),
    # Crystals / oscillators
    (re.compile(r'CRYSTAL|XTAL|ABM\d|NX\d|CSTCE|FA[SH]\d|ABRACON',
                re.IGNORECASE), ComponentType.CRYSTAL),
    # Fuses / polyfuses
    (re.compile(r'\bFUSE\b|POLYFUSE|PPTC|MF-|0ZCG|LVR', re.IGNORECASE), ComponentType.FUSE),
    # Test points
    (re.compile(r'TESTPOINT|TEST.POINT|TP_PAD', re.IGNORECASE), ComponentType.TESTPOINT),
    # Connectors
    (re.compile(r'\bCONN\b|HEADER|SOCKET|PLUG|\bJACK\b|RJ45|'
                r'USB.CON|MICRO.USB|TYPE.C|DSUB|DB\d',
                re.IGNORECASE), ComponentType.CONNECTOR),
]

# Pin names that confirm a switching regulator (even if part number doesn't match)
_SW_REG_PIN_NAMES = {'SW', 'SW1', 'SW2', 'SWITCH', 'LX', 'BOOST', 'BST', 'PH'}
# Pin names that confirm a protection diode (TVS/ESD)
_TVS_ESD_PART_TOKENS = {'TVS', 'ESD', 'PRTR', 'USBLC', 'CDSOT', 'ESDA', 'SMBJ'}


def classify_component(comp: "Component") -> None:
    """Populate component_type, value, value_str, and package in-place.

    Must be called after all pins have been added to the component.
    """
    pn = comp.part_number or ""

    # ── Package ──────────────────────────────────────────────────────────────
    m = _PACKAGE_RE.search(pn)
    if m:
        comp.package = m.group(1).upper().replace("-", "")

    # ── Value ────────────────────────────────────────────────────────────────
    value_si, value_str, _unit = _extract_value(pn)
    if value_si is not None:
        comp.value     = value_si
        comp.value_str = value_str

    # ── Component type: refdes prefix ────────────────────────────────────────
    ct = ComponentType.UNKNOWN
    for rx, ctype in _REFDES_TYPE_MAP:
        if rx.match(comp.refdes):
            ct = ctype
            break

    # Refine D-prefix: distinguish LED from TVS from plain diode
    if ct == ComponentType.DIODE:
        pn_up = pn.upper()
        if "LED" in pn_up:
            ct = ComponentType.LED
        # TVS/ESD stays as DIODE; callers check part_number for TVS/ESD keywords

    # ── Component type: part-number keywords (for UNKNOWN or IC) ─────────────
    if ct in (ComponentType.UNKNOWN, ComponentType.IC):
        for rx, ctype in _PARTNUM_TYPE_MAP:
            if rx.search(pn):
                ct = ctype
                break

    # ── Switching regulator via pin names ────────────────────────────────────
    if ct == ComponentType.IC:
        pin_names = {p.name.upper() for p in comp.pins}
        if pin_names & _SW_REG_PIN_NAMES:
            ct = ComponentType.REGULATOR

    comp.component_type = ct
