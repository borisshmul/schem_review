"""Entry point — launches the curses UI.

Can also be run with a file argument for headless mode:
    schem_review path/to/design.xml [--checks c1,c2] [--no-waivers]
"""
from __future__ import annotations

import argparse
import curses
import sys
from pathlib import Path


def _run_headless(path: str, check_names: list, use_waivers: bool) -> int:
    """Parse and run checks without the curses UI, printing to stdout."""
    from schem_review.checks import get_all_checks, run_checks
    from schem_review.output import write_json, write_log, write_md
    from schem_review.parser import ParseError, parse_file
    from schem_review.waivers import apply_waivers, load_waivers

    print("schem_review — headless mode")
    print(f"File: {path}")

    try:
        netlist = parse_file(path)
    except ParseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"Parsed: {len(netlist.components)} components, "
        f"{len(netlist.nets)} nets, "
        f"{len(netlist.sheets)} sheets"
    )

    if not check_names:
        check_names = [c["name"] for c in get_all_checks()]

    def progress(name: str) -> None:
        print(f"  Running: {name}")

    all_findings = run_checks(netlist, check_names, progress)

    # Apply waivers
    waived_entries: list = []
    if use_waivers:
        waivers = load_waivers(path)
        if waivers:
            print(f"\nWaivers loaded: {len(waivers)}")
        all_findings, waived_entries = apply_waivers(all_findings, waivers)

    # Severity breakdown
    from schem_review.model import Severity
    crit  = sum(1 for f in all_findings if f.severity == Severity.CRITICAL)
    errs  = sum(1 for f in all_findings if f.severity == Severity.ERROR)
    warns = sum(1 for f in all_findings if f.severity == Severity.WARN)
    infos = sum(1 for f in all_findings if f.severity == Severity.INFO)

    print(f"\nFindings: {len(all_findings)} active  ({crit} CRITICAL, {errs} ERROR, "
          f"{warns} WARN, {infos} INFO)")
    if waived_entries:
        print(f"Waived:   {len(waived_entries)} (see report Acknowledged section)")

    for f in all_findings:
        affected = ", ".join(f.affected) if f.affected else "—"
        conf_note = f"  [conf:{f.confidence:.0%}]" if f.confidence < 0.85 else ""
        print(
            f"  [{f.severity.value}] {f.check_name}: {f.message}  "
            f"(affected: {affected}){conf_note}"
        )

    log_path  = write_log(path, all_findings)
    md_path   = write_md(path, all_findings, waived=waived_entries)
    json_path = write_json(path, all_findings, waived=waived_entries)

    print(f"\nLog:      {log_path}")
    print(f"Markdown: {md_path}")
    print(f"JSON:     {json_path}")

    return 1 if crit > 0 or errs > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="schem_review",
        description="Xpedition schematic review tool",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Schematic file (.xml, .hkp, .net, .qcv, .txt) — omit to launch the interactive UI",
    )
    parser.add_argument(
        "--checks",
        metavar="NAMES",
        help="Comma-separated list of check names to run (headless mode only)",
        default="",
    )
    parser.add_argument(
        "--no-waivers",
        action="store_true",
        help="Ignore waivers.toml / waivers.json even if present",
        default=False,
    )
    args = parser.parse_args()

    if args.file:
        check_names = [c.strip() for c in args.checks.split(",") if c.strip()]
        sys.exit(_run_headless(args.file, check_names, not args.no_waivers))
    else:
        try:
            from schem_review.ui.app import App
            curses.wrapper(lambda stdscr: App(stdscr).run())
        except curses.error as exc:
            print(f"Terminal error: {exc}", file=sys.stderr)
            print("Try resizing your terminal or using headless mode: schem_review <file>",
                  file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
