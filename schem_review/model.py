"""Shared data model: Net, Pin, Component, Sheet, Netlist, Finding."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class PinDirection(Enum):
    IN = "IN"
    OUT = "OUT"
    PWR = "PWR"
    PASSIVE = "PASSIVE"
    BIDIR = "BIDIR"
    OC = "OC"        # open-collector / open-drain
    TRISTATE = "TRISTATE"
    UNSPEC = "UNSPEC"

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
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"


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


@dataclass
class Finding:
    id: str
    check_name: str
    severity: Severity
    message: str
    affected: List[str] = field(default_factory=list)
    sheet: str = ""
