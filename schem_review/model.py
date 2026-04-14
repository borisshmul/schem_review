"""Shared data model: Net, Pin, Component, Sheet, Netlist, Finding."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ComponentType(str, Enum):
    """Classified type of a schematic component."""
    UNKNOWN    = "UNKNOWN"
    IC         = "IC"
    RESISTOR   = "RESISTOR"
    CAPACITOR  = "CAPACITOR"
    INDUCTOR   = "INDUCTOR"
    LED        = "LED"
    DIODE      = "DIODE"
    CONNECTOR  = "CONNECTOR"
    TESTPOINT  = "TESTPOINT"
    FUSE       = "FUSE"
    FERRITE    = "FERRITE"
    CRYSTAL    = "CRYSTAL"
    TRANSISTOR = "TRANSISTOR"
    REGULATOR  = "REGULATOR"
    SWITCH     = "SWITCH"


class PinDirection(Enum):
    IN       = "IN"
    OUT      = "OUT"
    PWR      = "PWR"
    PASSIVE  = "PASSIVE"
    BIDIR    = "BIDIR"
    OC       = "OC"        # open-collector / open-drain
    TRISTATE = "TRISTATE"
    UNSPEC   = "UNSPEC"

    @classmethod
    def from_str(cls, s: str) -> "PinDirection":
        lookup: Dict[str, "PinDirection"] = {
            "IN": cls.IN,
            "INPUT": cls.IN,
            "OUT": cls.OUT,
            "OUTPUT": cls.OUT,
            "PWR": cls.PWR,
            "POWER": cls.PWR,
            "PWRIN": cls.PWR,
            "PWROUT": cls.PWR,
            "SUPPLY": cls.PWR,
            "PASSIVE": cls.PASSIVE,
            "BIDIR": cls.BIDIR,
            "BIDIRECTIONAL": cls.BIDIR,
            "INOUT": cls.BIDIR,
            "IO": cls.BIDIR,
            "OC": cls.OC,
            "OPENCOLLECTOR": cls.OC,
            "OPEN_COLLECTOR": cls.OC,
            "OPENDRAIN": cls.OC,
            "OPEN_DRAIN": cls.OC,
            "TRISTATE": cls.TRISTATE,
            "3STATE": cls.TRISTATE,
            "THREESTATE": cls.TRISTATE,
        }
        key = s.upper().strip().replace(" ", "").replace("-", "").replace("_", "")
        return lookup.get(key, cls.UNSPEC)


class Severity(Enum):
    CRITICAL = "CRITICAL"   # board will be destroyed or permanently non-functional
    ERROR    = "ERROR"      # board will not work as intended
    WARN     = "WARN"       # violates best practice; may work but is risky
    INFO     = "INFO"       # informational; no action required


@dataclass
class Pin:
    name: str
    number: str
    direction: PinDirection
    net: Optional[str]  # None or "" means unconnected
    component: str      # parent refdes


@dataclass
class Net:
    name: str
    pins: List[Pin] = field(default_factory=list)
    is_power: bool = False


@dataclass
class Component:
    refdes: str
    part_number: str
    pins: List[Pin] = field(default_factory=list)
    sheet: str = ""
    # Populated by component_classifier after parsing
    component_type: ComponentType = field(default_factory=lambda: ComponentType.UNKNOWN)
    value: Optional[float] = None   # base SI unit: Ω / F / H / V
    value_str: str = ""             # original string, e.g. "100nF", "4K7"
    package: str = ""               # e.g. "0402", "SOT-23"

    def pin_by_number(self, number: str) -> Optional[Pin]:
        for p in self.pins:
            if p.number == number:
                return p
        return None

    def pin_by_name(self, name: str) -> Optional[Pin]:
        for p in self.pins:
            if p.name.upper() == name.upper():
                return p
        return None


@dataclass
class Sheet:
    name: str
    components: List[Component] = field(default_factory=list)


@dataclass
class Netlist:
    components: Dict[str, Component] = field(default_factory=dict)  # refdes -> Component
    nets: Dict[str, Net] = field(default_factory=dict)              # net name -> Net
    sheets: Dict[str, Sheet] = field(default_factory=dict)          # sheet name -> Sheet
    source_file: str = ""
    duplicate_refdes: List[str] = field(default_factory=list)       # refdes seen more than once


@dataclass
class Finding:
    id: str
    check_name: str
    severity: Severity
    message: str
    affected: List[str] = field(default_factory=list)
    sheet: str = ""
    confidence: float = 1.0   # 0.0–1.0; heuristic checks use < 1.0
