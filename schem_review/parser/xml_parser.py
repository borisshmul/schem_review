"""Xpedition iCDB XML export parser.

Uses iterparse for memory-efficient processing of large designs.
Handles multiple XML dialect variations produced by different Xpedition versions.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Set

from schem_review.model import Component, Net, Netlist, Pin, PinDirection, Sheet
from schem_review.parser import ParseError

# ---------------------------------------------------------------------------
# Tag / attribute name flexibility
# ---------------------------------------------------------------------------

_COMPONENT_TAGS: Set[str] = {
    "component", "compinstance", "instance", "partinstance",
    "schcomponent", "schinstance", "symbol", "symbolinstance",
    "part", "comp", "refdes",
}
_PIN_TAGS: Set[str] = {
    "pin", "pininstance", "schpin", "pinref", "comppin", "pindescription",
    "pinobj",
}
_NET_TAGS: Set[str] = {
    "net", "netobj", "schnet", "netsegment", "wire", "signal",
}
_SHEET_TAGS: Set[str] = {
    "sheet", "schematic", "page", "schpage", "schempage", "drawing",
}

# Possible attribute names for each field
_REFDES_ATTRS = ["refdess", "refdes", "ref", "designator", "name", "refname", "instancename"]
_PARTNUM_ATTRS = ["partnumber", "partref", "compref", "cellref", "value", "parttype", "type",
                  "partname", "symbol"]
_PIN_NUM_ATTRS = ["pinnumber", "pinnum", "number", "num", "pin", "id"]
_PIN_NAME_ATTRS = ["pinname", "name", "label", "pinlabel", "pindesignator"]
_PIN_TYPE_ATTRS = ["pintype", "direction", "type", "iotype", "pindirection", "electrical"]
_NET_NAME_ATTRS = ["netname", "net", "name", "signal", "signalname"]
_SHEET_NAME_ATTRS = ["name", "sheetname", "pagename", "id", "title"]


def _first_attr(elem: ET.Element, candidates: List[str]) -> Optional[str]:
    """Return the first matching attribute value (case-insensitive key match)."""
    lower_map = {k.lower(): v for k, v in elem.attrib.items()}
    for c in candidates:
        v = lower_map.get(c.lower())
        if v is not None:
            return v.strip()
    return None


def _local(tag: str) -> str:
    """Strip XML namespace prefix."""
    return tag.split("}")[-1].lower() if "}" in tag else tag.lower()


# ---------------------------------------------------------------------------
# Parser state machine
# ---------------------------------------------------------------------------

class _ParseState:
    def __init__(self) -> None:
        self.netlist = Netlist()
        self.current_sheet: Optional[str] = None
        self.current_comp: Optional[Component] = None
        # pin refs: list of (comp_refdes, pin_number) per net
        self._net_pin_refs: Dict[str, List[tuple]] = {}

    # -- helpers -------------------------------------------------------

    def _ensure_sheet(self, name: str) -> Sheet:
        if name not in self.netlist.sheets:
            self.netlist.sheets[name] = Sheet(name=name)
        return self.netlist.sheets[name]

    def _ensure_net(self, name: str) -> Net:
        if name not in self.netlist.nets:
            self.netlist.nets[name] = Net(name=name)
        return self.netlist.nets[name]

    def finalize(self) -> None:
        """Cross-reference pin↔net associations after parsing is complete."""
        # Walk every component pin and register it in its net
        for comp in self.netlist.components.values():
            for pin in comp.pins:
                if pin.net:
                    net = self._ensure_net(pin.net)
                    # Avoid duplicates
                    already = any(
                        p.component == pin.component and p.number == pin.number
                        for p in net.pins
                    )
                    if not already:
                        net.pins.append(pin)

        # Mark power nets
        for net in self.netlist.nets.values():
            pwr_pins = [p for p in net.pins if p.direction == PinDirection.PWR]
            if pwr_pins or _looks_like_power_net(net.name):
                net.is_power = True

        # Handle explicit net→pin refs collected from <Net> elements
        for net_name, refs in self._net_pin_refs.items():
            net = self._ensure_net(net_name)
            for (refdes, pin_num) in refs:
                comp = self.netlist.components.get(refdes)
                if comp is None:
                    continue
                pin = comp.pin_by_number(pin_num)
                if pin is None:
                    continue
                if pin.net is None or pin.net == "":
                    pin.net = net_name
                already = any(
                    p.component == pin.component and p.number == pin.number
                    for p in net.pins
                )
                if not already:
                    net.pins.append(pin)


def _looks_like_power_net(name: str) -> bool:
    u = name.upper().replace("_", "").replace("-", "")
    return any(tok in u for tok in ["VCC", "VDD", "VEE", "VSS", "GND", "POWER", "PWR"])


# ---------------------------------------------------------------------------
# Two-pass iterparse implementation
# ---------------------------------------------------------------------------

def parse_xml(path: str) -> Netlist:
    """Parse an Xpedition iCDB XML export file.

    Raises ParseError on unrecoverable issues.
    """
    p = Path(path)
    if not p.exists():
        raise ParseError(f"File not found: {path}")

    state = _ParseState()
    state.netlist.source_file = str(p)

    try:
        _pass_components(path, state)
        _pass_nets(path, state)
        state.finalize()
    except ET.ParseError as exc:
        raise ParseError(f"XML parse error in '{path}': {exc}") from exc

    # If nothing was found, try the flat/mixed strategy
    if not state.netlist.components:
        state = _ParseState()
        state.netlist.source_file = str(p)
        _pass_flat(path, state)
        state.finalize()

    from schem_review.component_classifier import classify_component
    for comp in state.netlist.components.values():
        classify_component(comp)

    return state.netlist


def _pass_components(path: str, state: _ParseState) -> None:
    """First pass: extract components and their pins."""
    sheet_stack: List[str] = []

    for event, elem in ET.iterparse(path, events=("start", "end")):
        local = _local(elem.tag)

        if event == "start":
            if local in _SHEET_TAGS:
                sheet_name = _first_attr(elem, _SHEET_NAME_ATTRS) or f"Sheet{len(state.netlist.sheets)+1}"
                sheet_stack.append(sheet_name)
                state._ensure_sheet(sheet_name)

            elif local in _COMPONENT_TAGS:
                refdes = _first_attr(elem, _REFDES_ATTRS)
                if refdes:
                    part = _first_attr(elem, _PARTNUM_ATTRS) or ""
                    sheet = sheet_stack[-1] if sheet_stack else "Sheet1"
                    comp = Component(refdes=refdes, part_number=part, sheet=sheet)
                    if refdes in state.netlist.components:
                        if refdes not in state.netlist.duplicate_refdes:
                            state.netlist.duplicate_refdes.append(refdes)
                    state.netlist.components[refdes] = comp
                    state._ensure_sheet(sheet).components.append(comp)
                    state.current_comp = comp

            elif local in _PIN_TAGS and state.current_comp is not None:
                _parse_pin_elem(elem, state.current_comp)

        else:  # end
            if local in _SHEET_TAGS and sheet_stack:
                sheet_stack.pop()
            elif local in _COMPONENT_TAGS:
                state.current_comp = None

        # Free memory
        if event == "end":
            elem.clear()


def _pass_nets(path: str, state: _ParseState) -> None:
    """Second pass: extract net→pin references from <Net> elements."""
    current_net: Optional[str] = None

    for event, elem in ET.iterparse(path, events=("start", "end")):
        local = _local(elem.tag)

        if event == "start":
            if local in _NET_TAGS:
                net_name = _first_attr(elem, _NET_NAME_ATTRS)
                if net_name:
                    current_net = net_name
                    state._ensure_net(net_name)

            elif local in ("pinref", "connection", "pinconn", "netpin") and current_net:
                refdes = _first_attr(elem, _REFDES_ATTRS)
                pin_num = _first_attr(elem, _PIN_NUM_ATTRS)
                if refdes and pin_num:
                    refs = state._net_pin_refs.setdefault(current_net, [])
                    refs.append((refdes, pin_num))

        else:
            if local in _NET_TAGS:
                current_net = None

        if event == "end":
            elem.clear()


def _pass_flat(path: str, state: _ParseState) -> None:
    """Fallback: walk the entire tree and extract anything that looks like a component/pin/net."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise ParseError(f"XML parse error: {exc}") from exc

    root = tree.getroot()
    _walk_flat(root, state, sheet="Sheet1")


def _walk_flat(elem: ET.Element, state: _ParseState, sheet: str) -> None:
    local = _local(elem.tag)

    if local in _SHEET_TAGS:
        sheet = _first_attr(elem, _SHEET_NAME_ATTRS) or sheet
        state._ensure_sheet(sheet)

    elif local in _COMPONENT_TAGS:
        refdes = _first_attr(elem, _REFDES_ATTRS)
        if refdes and refdes not in state.netlist.components:
            part = _first_attr(elem, _PARTNUM_ATTRS) or ""
            comp = Component(refdes=refdes, part_number=part, sheet=sheet)
            state.netlist.components[refdes] = comp
            state._ensure_sheet(sheet).components.append(comp)
            # Parse child pins
            for child in elem:
                if _local(child.tag) in _PIN_TAGS:
                    _parse_pin_elem(child, comp)
        return  # don't recurse inside — already handled children

    elif local in _NET_TAGS:
        net_name = _first_attr(elem, _NET_NAME_ATTRS)
        if net_name:
            state._ensure_net(net_name)
            for child in elem:
                cl = _local(child.tag)
                if cl in ("pinref", "connection", "pinconn", "netpin"):
                    refdes = _first_attr(child, _REFDES_ATTRS)
                    pin_num = _first_attr(child, _PIN_NUM_ATTRS)
                    if refdes and pin_num:
                        state._net_pin_refs.setdefault(net_name, []).append((refdes, pin_num))
        return

    for child in elem:
        _walk_flat(child, state, sheet)


def _parse_pin_elem(elem: ET.Element, comp: Component) -> None:
    """Extract a Pin from a pin element and attach it to the component."""
    pin_num = _first_attr(elem, _PIN_NUM_ATTRS) or ""
    pin_name = _first_attr(elem, _PIN_NAME_ATTRS) or pin_num
    dir_str = _first_attr(elem, _PIN_TYPE_ATTRS) or "UNSPEC"
    net_name = _first_attr(elem, _NET_NAME_ATTRS)

    # Avoid duplicate pin numbers
    if pin_num and comp.pin_by_number(pin_num) is not None:
        return

    pin = Pin(
        name=pin_name,
        number=pin_num,
        direction=PinDirection.from_str(dir_str),
        net=net_name if net_name else None,
        component=comp.refdes,
    )
    comp.pins.append(pin)
