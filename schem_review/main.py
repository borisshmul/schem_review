"""Entry point — launches the curses UI.

Can also be run with a file argument for headless mode:
    schem_review path/to/design.xml [--checks c1,c2]
"""
from __future__ import annotations

import argparse
import curses
import sys
from pathlib import Path


def _run_headless(path: str, check_names: list) -> int:
    """Parse and run checks without the curses UI, printing to stdout."""
    from schem_review.checks import get_all_checks, run_checks
    from schem_review.output import write_log, write_md
    from schem_review.parser import ParseError, parse_file

    print(f"schem_review — headless mode")
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

    findings = run_checks(netlist, check_names, progress)

    print(f"\nFindings: {len(findings)}")
    for f in findings:
        affected = ", ".join(f.affected) if f.affected else "—"
        print(f"  [{f.severity.value}] {f.check_name}: {f.message}  (affected: {affected})")

    log_path = write_log(path, findings)
    md_path = write_md(path, findings)
    print(f"\nLog:      {log_path}")
    print(f"Markdown: {md_path}")

    errors = sum(1 for f in findings if f.severity.value == "ERROR")
    return 1 if errors > 0 else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="schem_review",
        description="Xpedition schematic review tool",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Schematic file (.xml or .hkp) — omit to launch the interactive UI",
    )
    parser.add_argument(
        "--checks",
        metavar="NAMES",
        help="Comma-separated list of check names to run (headless mode only)",
        default="",
    )
    args = parser.parse_args()

    if args.file:
        # Headless mode
        check_names = [c.strip() for c in args.checks.split(",") if c.strip()]
        sys.exit(_run_headless(args.file, check_names))
    else:
        # Interactive curses UI
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
