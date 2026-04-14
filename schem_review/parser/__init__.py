"""Parser package — auto-detects format from file extension."""
from __future__ import annotations

from pathlib import Path

from schem_review.model import Netlist


class ParseError(Exception):
    """Raised when a file cannot be parsed."""


def parse_file(path: str) -> Netlist:
    """Parse a schematic file; auto-detect format from extension.

    Raises ParseError with a human-readable message on failure.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".xml":
        from schem_review.parser.xml_parser import parse_xml
        return parse_xml(str(p))
    elif ext in (".hkp", ".net", ".netlist", ".qcv", ".txt"):
        from schem_review.parser.hkp_parser import parse_hkp
        return parse_hkp(str(p))
    else:
        raise ParseError(
            f"Unsupported file extension '{ext}'. Expected .xml, .hkp, .net, .qcv, or .txt"
        )


__all__ = ["parse_file", "ParseError"]
