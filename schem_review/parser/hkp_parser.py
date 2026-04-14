"""Xpedition HKP netlist parser.

Streams the file line-by-line for memory efficiency.
Handles three common HKP / Mentor netlist dialects:

  1. PADS netlist  (*PADS-NETLIST*, *PART*, *NET*, *SIGNAL*)
  2. Mentor/Xpedition HKP  (!COMPONENT_SECTION, !NET_SECTION, or bare keywords)
  3. Allegro-style  ($PART, $NET, $SIGNAL)

Each dialect uses the same internal state machine; only the section-
header detection differs.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from schem_review.model import Component, Net, Netlist, Pin, PinDirection, Sheet
from schem_review.parser import ParseError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NC_MARKERS = {"NC", "NOCONNECT", "NO_CONNECT", "UNCONNECTED", "?"}


def _is_nc(net: str) -> bool:
    return net.upper().replace(" ", "").replace("_", "") in _NC_MARKERS


def _looks_like_power(name: str) -> bool:
    u = name.upper().replace("_", "")
    return any(t in u for t in ["VCC", "VDD", "VEE", "VSS", "GND", "PWR", "POWER"])


# Pin entry patterns for various dialects:
#   <pin_num> <net_name> [direction] [pin_name]
#   <pin_name> <pin_num> <net_name> [direction]
#   <refdes>.<pin_num> (in net sections)
_PIN_LINE_RE = re.compile(
    r"^\s*(?P<a>\S+)\s+(?P<b>\S+)(?:\s+(?P<c>\S+))?(?:\s+(?P<d>\S+))?\s*$"
)
_REFDES_PIN_DOT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)[\.\-](\S+)$")
_REFDES_PIN_SPACE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s+(\S+)$")


# ---------------------------------------------------------------------------
# Dialect detection
# ---------------------------------------------------------------------------

class _Dialect:
    PADS = "PADS"       # *PADS-NETLIST*  *PART*  *NET*  *SIGNAL*
    MENTOR = "MENTOR"   # !COMPONENT_SECTION  !NET_SECTION  .PART  .NET
    ALLEGRO = "ALLEGRO" # $PART  $NET  $SIGNAL
    GENERIC = "GENERIC" # fallback: bare PART / NET / SIGNAL keywords


def _detect_dialect(lines: List[str]) -> str:
    for line in lines[:50]:
        s = line.strip().upper()
        if s.startswith("*PADS"):
            return _Dialect.PADS
        if s.startswith("!") or s.startswith(".NETLIST") or s.startswith(".PART"):
            return _Dialect.MENTOR
        if s.startswith("$PART") or s.startswith("$NET") or s.startswith("$SIGNAL"):
            return _Dialect.ALLEGRO
    return _Dialect.GENERIC


# ---------------------------------------------------------------------------
# Section tokens per dialect
# ---------------------------------------------------------------------------

_SECTION_TOKENS = {
    _Dialect.PADS: {
        "part": {"*PART*"},
        "net": {"*NET*"},
        "signal": {"*SIGNAL*"},
        "end": {"*END*", "*REMARK*"},
    },
    _Dialect.MENTOR: {
        "part": {"!COMPONENT_SECTION", ".PART", "PART", ".PARTLIST"},
        "net": {"!NET_SECTION", ".NET", "NET", ".NETLIST", ".NETLISTEX"},
        "signal": {"!SIGNAL", "NET"},
        "end": {"!END", ".END", ".ENDPART", ".ENDNET", ".ENDNETLIST", ".ENDNETLISTEX"},
    },
    _Dialect.ALLEGRO: {
        "part": {"$PART", "$PARTS"},
        "net": {"$NET", "$NETS"},
        "signal": {"$SIGNAL"},
        "end": {"$END", "$ENDNETS", "$ENDPARTS"},
    },
    _Dialect.GENERIC: {
        "part": {"PART", "PARTS", "COMPONENT", "COMPONENTS", ".PART"},
        "net": {"NET", "NETS", ".NET", "NETLIST"},
        "signal": {"SIGNAL", "NET"},
        "end": {"END", ".END", "ENDPART", "ENDNET"},
    },
}


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_hkp(path: str) -> Netlist:
    """Parse a HKP / PADS / Mentor netlist file.

    Raises ParseError on unrecoverable issues.
    """
    p = Path(path)
    if not p.exists():
        raise ParseError(f"File not found: {path}")

    try:
        with open(str(p), encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        raise ParseError(f"Cannot read '{path}': {exc}") from exc

    dialect = _detect_dialect(lines)
    tokens = _SECTION_TOKENS[dialect]

    netlist = Netlist(source_file=str(p))
    _do_parse(lines, tokens, dialect, netlist)
    _finalize(netlist)
    from schem_review.component_classifier import classify_component
    for comp in netlist.components.values():
        classify_component(comp)
    return netlist


def _do_parse(lines: List[str], tokens: Dict, dialect: str, netlist: Netlist) -> None:  # noqa: C901
    """State-machine line parser."""
    # State
    in_parts = False
    in_nets = False
    current_net: Optional[str] = None
    current_comp: Optional[Component] = None

    # Pending pin-to-net associations when net section comes after part section
    # Maps (refdes, pin_num_or_name) -> net_name
    pin_net_map: Dict[Tuple[str, str], str] = {}

    for raw in lines:
        line = raw.rstrip("\r\n")
        stripped = line.strip()

        # Skip empty and comment lines
        if not stripped or stripped.startswith(("//", "#", ";")):
            continue

        upper = stripped.upper()

        # ---- section transitions ----------------------------------------

        if any(upper == t or upper.startswith(t + " ") for t in tokens["part"]):
            in_parts = True
            in_nets = False
            current_net = None
            current_comp = None
            continue

        if any(upper == t or upper.startswith(t + " ") for t in tokens["net"]):
            in_parts = False
            in_nets = True
            current_net = None
            current_comp = None
            continue

        if any(upper == t or upper.startswith(t + " ") or upper.startswith(t.rstrip("*") + "*")
               for t in tokens["end"]):
            # End of current section
            if in_parts:
                current_comp = None
            in_parts = False
            in_nets = False
            current_net = None
            current_comp = None
            continue

        # ---- part section -----------------------------------------------

        if in_parts:
            # Detect start of new component block or inline component
            # Formats:
            #   REFDES PARTTYPE [SHEET]          (one-liner)
            #   .PART REFDES PARTTYPE            (Mentor)
            #   REFDES PARTTYPE                  (followed by pin lines)
            comp_line = stripped.lstrip(".")
            if dialect == _Dialect.MENTOR and upper.startswith("PART "):
                comp_line = stripped[5:].strip()

            parts = comp_line.split()
            if not parts:
                continue

            # If line is indented and we have a current_comp, treat as pin line
            if line.startswith((" ", "\t")) and current_comp is not None:
                _parse_pin_line(parts, current_comp, pin_net_map)
                continue

            # Otherwise: start a new component (unless only one token and looks like a pin)
            if len(parts) >= 2:
                # Heuristic: first token is refdes (starts with letter, not a section keyword)
                tok0_upper = parts[0].upper().lstrip(".")
                if tok0_upper in {t.lstrip("*$!.") for tset in tokens.values() for t in tset}:
                    continue  # it's a section keyword, skip
                refdes = parts[0].lstrip(".")
                parttype = parts[1] if len(parts) > 1 else ""
                sheet = parts[2] if len(parts) > 2 else "Sheet1"
                if not refdes[0].isalpha() and refdes[0] != "_":
                    continue  # not a valid refdes
                comp = Component(refdes=refdes, part_number=parttype, sheet=sheet)
                if refdes in netlist.components:
                    if refdes not in netlist.duplicate_refdes:
                        netlist.duplicate_refdes.append(refdes)
                netlist.components[refdes] = comp
                _ensure_sheet(netlist, sheet).components.append(comp)
                current_comp = comp

        # ---- net section ------------------------------------------------

        elif in_nets:
            # New signal/net declaration
            # PADS:   *SIGNAL* NET_NAME
            # Mentor: .NET NET_NAME  or just  NET_NAME  (new net header line)
            # Allegro: $SIGNAL NET_NAME

            is_signal_kw = any(
                upper == t or upper.startswith(t + " ")
                for t in tokens.get("signal", set())
            )
            if is_signal_kw:
                # Extract net name after keyword
                parts = stripped.split(None, 1)
                current_net = parts[1].strip() if len(parts) > 1 else None
                if current_net:
                    _ensure_net(netlist, current_net)
                continue

            # Mentor / generic: unindented line = net name header, indented = pin refs
            if not line.startswith((" ", "\t")):
                # Could be a bare net name line (Mentor style)
                parts_s = stripped.split()
                if len(parts_s) == 1 and not _looks_like_refdes_pin(stripped):
                    current_net = stripped
                    _ensure_net(netlist, current_net)
                    continue
                # Could be "NET_NAME" or "REFDES PIN" on same non-indented line
                if len(parts_s) >= 2:
                    # Try: net_name on its own
                    # or: refdes.pinnum  refdes.pinnum  ...
                    if "." in parts_s[0] or "-" in parts_s[0]:
                        # pin refs on the current net
                        if current_net:
                            for tok in parts_s:
                                _register_net_pin(tok, current_net, netlist, pin_net_map)
                    else:
                        # First token may be net name
                        current_net = parts_s[0]
                        _ensure_net(netlist, current_net)
                        for tok in parts_s[1:]:
                            _register_net_pin(tok, current_net, netlist, pin_net_map)
                    continue

            # Indented line: pin refs for current net
            if current_net:
                parts_s = stripped.split()
                for tok in parts_s:
                    _register_net_pin(tok, current_net, netlist, pin_net_map)

    # Apply collected pin→net associations
    for (refdes, pin_key), net_name in pin_net_map.items():
        comp = netlist.components.get(refdes)
        if comp is None:
            continue
        pin = comp.pin_by_number(pin_key) or comp.pin_by_name(pin_key)
        if pin is not None and (pin.net is None or pin.net == ""):
            pin.net = net_name


def _looks_like_refdes_pin(s: str) -> bool:
    return bool(_REFDES_PIN_DOT.match(s))


def _parse_pin_line(parts: List[str], comp: Component, pin_net_map: Dict) -> None:
    """Parse an indented pin line inside a component block.

    Supported formats:
      <pin_num> <net_name> [direction] [pin_name]
      <pin_name> <pin_num> <net_name> [direction]
    """
    if len(parts) < 2:
        return

    # Try format: pin_number net_name [direction] [pin_name]
    pin_num = parts[0]
    net_name = parts[1] if len(parts) > 1 else ""
    direction_str = parts[2] if len(parts) > 2 else "UNSPEC"
    pin_name = parts[3] if len(parts) > 3 else pin_num

    # If direction_str doesn't look like a direction, try swapped
    if len(parts) == 3 and PinDirection.from_str(parts[2]) == PinDirection.UNSPEC:
        pin_name = parts[2]
        direction_str = "UNSPEC"

    direction = PinDirection.from_str(direction_str)
    net = net_name if net_name and not _is_nc(net_name) else None

    # Skip if pin already exists
    if comp.pin_by_number(pin_num) is not None:
        return

    pin = Pin(
        name=pin_name,
        number=pin_num,
        direction=direction,
        net=net,
        component=comp.refdes,
    )
    comp.pins.append(pin)
    if net:
        pin_net_map[(comp.refdes, pin_num)] = net


def _register_net_pin(token: str, net_name: str, netlist: Netlist, pin_net_map: Dict) -> None:
    """Register a pin-ref token (REFDES.PIN or REFDES-PIN) on a net."""
    m = _REFDES_PIN_DOT.match(token)
    if not m:
        # Try REFDES PIN (space-separated already split)
        return
    refdes, pin_key = m.group(1), m.group(2)
    pin_net_map[(refdes, pin_key)] = net_name

    net = netlist.nets.get(net_name)
    if net is None:
        return
    comp = netlist.components.get(refdes)
    if comp is None:
        # Create a stub component so the net has a reference
        comp = Component(refdes=refdes, part_number="", sheet="Sheet1")
        netlist.components[refdes] = comp
        _ensure_sheet(netlist, "Sheet1").components.append(comp)

    pin = comp.pin_by_number(pin_key) or comp.pin_by_name(pin_key)
    if pin is None:
        pin = Pin(
            name=pin_key,
            number=pin_key,
            direction=PinDirection.UNSPEC,
            net=net_name,
            component=refdes,
        )
        comp.pins.append(pin)
    else:
        if pin.net is None or pin.net == "":
            pin.net = net_name

    already = any(p.component == refdes and p.number == pin_key for p in net.pins)
    if not already:
        net.pins.append(pin)


def _ensure_sheet(netlist: Netlist, name: str) -> Sheet:
    if name not in netlist.sheets:
        netlist.sheets[name] = Sheet(name=name)
    return netlist.sheets[name]


def _ensure_net(netlist: Netlist, name: str) -> Net:
    if name not in netlist.nets:
        netlist.nets[name] = Net(name=name)
    return netlist.nets[name]


def _finalize(netlist: Netlist) -> None:
    """Build net.pins lists and mark power nets."""
    # Ensure all nets referenced by pins are present and linked
    for comp in netlist.components.values():
        for pin in comp.pins:
            if pin.net and not _is_nc(pin.net):
                net = _ensure_net(netlist, pin.net)
                already = any(p.component == pin.component and p.number == pin.number
                              for p in net.pins)
                if not already:
                    net.pins.append(pin)

    for net in netlist.nets.values():
        if _looks_like_power(net.name):
            net.is_power = True
