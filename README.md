<div align="center">

# schem_review

**Automated schematic linter for Xpedition EDA designs.**

[![Build](https://img.shields.io/badge/build-passing-brightgreen?style=flat-square)](https://github.com/redrussian1917/schem_review/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue?style=flat-square)](https://www.python.org/)
[![Checks: 37 rules](https://img.shields.io/badge/checks-37%20rules-orange?style=flat-square)](#-check-catalog)
[![Input: iCDB XML · HKP](https://img.shields.io/badge/input-iCDB%20XML%20%7C%20HKP-lightgrey?style=flat-square)](#supported-file-formats)

---

**Catch unconnected pins, broken differential pairs, cross-domain voltage signals,
power sequencing cycles, and 33 other design errors in your netlist —
before they become a $4,000 PCB respin.**

</div>

---

## See It in Action

Running against the included sample design:

```
$ schem_review samples/stm32_eth_test.xml

schem_review — headless mode
File: samples/stm32_eth_test.xml
Parsed: 21 components, 38 nets, 3 sheets

  Running: unconnected_pins
  Running: floating_inputs
  ...
  Running: voltage_domain_crossing
  Running: reset_domain_analysis

Findings: 27 active  (1 CRITICAL, 4 ERROR, 18 WARN, 4 INFO)

  [CRITICAL] voltage_domain_crossing: Net 'UART1_TX' connects 3.3V (U1) vs 1.8V (U3) — no level-shifter
  [ERROR]    reset_domain_analysis: Reset net 'nRESET' has no driver — state is undefined
  [ERROR]    unconnected_pins: U1 pin 25 (PC0) is unconnected
  ...

Log:      samples/stm32_eth_test_review_20260413_120000.log
Markdown: samples/stm32_eth_test_review_20260413_120000.md
JSON:     samples/stm32_eth_test_review_20260413_120000.json
```

Exit codes: **2** = CRITICAL findings · **1** = ERROR findings · **0** = clean

---

## Key Features

- **Voltage domain crossing detection** — infers supply voltage from rail names (VDD_3V3, VCC_1V8, etc.) and flags signal nets that span different domains without a level-shifter. Silent latch-up risk caught before layout.

- **Power sequencing graph** — builds an enable-chain graph from `EN`/`PGOOD` nets across all regulators; detects cycles (latch conditions that prevent any rail from starting) as CRITICAL.

- **Reset domain analysis** — validates every RST/RESET net: single driver, at least one receiver, and consistent active-polarity naming between net and pin.

- **SPI mode consistency** — groups devices by shared SCK net and checks that explicit CPOL/CPHA pins are consistently tied across master and slaves.

- **Confidence-ranked findings** — every heuristic check carries a confidence score (0–1). Scores below 0.90 are automatically downgraded; below 0.60 are suppressed in normal mode. Use `--verbose` to surface everything.

- **Waiver discipline** — a waiver without both `reason` and `author` fields is re-emitted as INFO with a "waived without justification" tag, so approvals cannot be silently granted.

- **Protocol-aware linting** — dedicated rule sets for I²C (pull-up pairing, address conflicts, rise-time), SPI (bus completeness, mode consistency), UART (TX/RX crossing), SGMII (AC-coupling, DC bias, termination, polarity), RGMII (bus completeness, voltage domain, series resistors), MDI (Bob Smith termination), and MDIO (pull-ups, PHY address conflicts, reset sequencing).

- **Power & ground discipline** — LED current limiting (CRITICAL), switching regulator completeness (CRITICAL), bulk and HF decoupling hierarchy, VDDA isolation, ESD on external nets.

- **Graded exit codes for CI/CD** — exit `2` on CRITICAL, `1` on ERROR, `0` for clean. Gate your pipeline at the granularity you need.

- **Interactive TUI + headless CI mode** — full curses UI with animated Armi the armadillo, category-grouped check picker, and live recursive file search. Or run headless.

- **Zero hard dependencies** — pure Python standard library.

---

## Quick Start

```bash
# Install (requires Python ≥ 3.8)
pip install .
# or: uv tool install .

# Interactive TUI
schem_review

# Headless — run all checks, exit 2 on CRITICAL / 1 on ERROR
schem_review path/to/design.xml

# Include low-confidence heuristic findings
schem_review design.xml --verbose

# Targeted check subset, skip waivers
schem_review design.xml --checks voltage_domain_crossing,reset_domain_analysis --no-waivers
```

Output files are written alongside the input automatically:
`design_review_<timestamp>.md`, `.log`, and `.json`

---

## Check Catalog

| Category | # | Checks |
|---|:-:|---|
| **DRC** | 9 | `unconnected_pins` · `floating_inputs` · `power_pin_conflicts` · `missing_decoupling_caps` · `net_naming_consistency` · `single_pin_nets` · `duplicate_refdes` · `net_fanout` · `refdes_numbering_gaps` |
| **EE** | 8 | `i2c_signals` · `usb_dp_pullup` · `crystal_load_caps` · `diff_pair_component_level` · `power_enable_undriven` · `i2c_address_conflicts` · `i2c_pullup_speed` · `test_coverage_score` |
| **POWER** | 6 | `led_missing_current_limit` · `switching_regulator_completeness` · `bulk_cap_on_power_input` · `vdda_isolation` · `decoupling_hierarchy` · `esd_protection_external` |
| **INTEGRITY** | 4 | `voltage_domain_crossing` · `reset_domain_analysis` · `power_sequencing` · `spi_mode_consistency` |
| **ETHERNET** | 10 | `sgmii_differential_pairs` · `sgmii_dc_bias` · `sgmii_termination` · `sgmii_polarity_swap` · `rgmii_bus_completeness` · `rgmii_series_termination` · `rgmii_voltage_domain` · `mdi_bob_smith_termination` · `mdi_pair_association` · `mdio_pullup` |

All checks carry a **confidence score** (0–1). Heuristic-based checks use scores below 0.90, which automatically downgrade or suppress findings to reduce warning fatigue:

| Confidence | Effect |
|---|---|
| ≥ 0.90 | Full severity — emitted as-is |
| 0.75 – 0.89 | Downgraded one level (e.g. ERROR → WARN) |
| 0.60 – 0.74 | Downgraded two levels, tagged `[heuristic]` |
| < 0.60 | Suppressed in normal mode; shown as INFO with `--verbose` |

---

## UI Reference

### Global keys

| Key | Action |
|---|---|
| `1` / `2` | Switch to SETUP / RESULTS tab |
| `Tab` | Switch focus between panels |
| `R` | Run selected checks |
| `F1` | Keyboard shortcut help |
| `F2` | Toggle Armi mascot panel |
| `Q` | Quit |

### SETUP tab — Files panel (left)

| Key | Action |
|---|---|
| `↑` `↓` | Navigate entries |
| `→` or `↵` | Enter directory / select file |
| `←` or `⌫` | Go up to parent directory |
| `/` | Start search (recursive across entire tree) |
| any letter/symbol | Start search immediately (no `/` needed) |
| `⌫` (in search, empty bar) | Exit search bar |
| `Esc` | Clear and exit search |
| `*` / `?` | Glob wildcards in search (e.g. `*.xml`, `design*`) |
| `PgUp` `PgDn` | Fast scroll |

### SETUP tab — Checks panel (right)

| Key | Action |
|---|---|
| `↑` `↓` | Navigate check list |
| `Space` | Toggle check on / off |
| `A` | Select ALL checks |
| `N` | Deselect ALL checks |

### RESULTS tab

| Key | Action |
|---|---|
| `↑` `↓` | Navigate findings |
| `↵` | Expand / collapse section |
| `PgUp` `PgDn` | Fast scroll |

---

## Waiver File Format

Place a `waivers.toml` (preferred) or `waivers.json` next to your design file.
**Both `reason` and `author` are required** — a waiver without either is
re-emitted as INFO with a "waived without justification" note.

```toml
[[waiver]]
check  = "single_pin_nets"
net    = "REG_EN#"
reason = "Pulled high via board strap — not on schematic"
author = "B.S."
date   = "2026-04-13"

[[waiver]]
check  = "esd_protection_external"
net    = "UART1_TX"
reason = "Internal board-to-board connector — not externally accessible"
author = "B.S."
date   = "2026-04-13"
```

---

## Adding a Custom Check

```python
# schem_review/checks/my_checks.py
from schem_review.checks.registry import register
from schem_review.model import Finding, Netlist, Severity

@register("Flag connectors that have no mating part number defined", category="EE")
def connector_mating_parts(netlist: Netlist) -> list[Finding]:
    findings = []
    for refdes, comp in netlist.components.items():
        if refdes.upper().startswith("J") and not comp.part_number:
            findings.append(Finding(
                id=f"no_mating_{refdes}",
                check_name="connector_mating_parts",
                severity=Severity.WARN,
                message=f"{refdes} has no part number / mating connector defined",
                affected=[refdes],
                sheet=comp.sheet,
            ))
    return findings
```

Register it in `schem_review/checks/__init__.py`:

```python
from schem_review.checks import drc, ee, ethernet, integrity, my_checks, power  # noqa: F401
```

The check appears automatically in the TUI and headless mode.

---

## Project Layout

```
schem_review/
├── parser/
│   ├── xml_parser.py          # iCDB XML → Netlist (iterparse, multi-dialect)
│   └── hkp_parser.py          # Xpedition HKP / PADS / Allegro → Netlist
├── checks/
│   ├── registry.py            # @register decorator and check runner
│   ├── drc.py                 # Structural DRC (9 rules)
│   ├── ee.py                  # EE conventions (8 rules)
│   ├── power.py               # Power system (6 rules)
│   ├── integrity.py           # Integrity: voltage domains, reset, sequencing, SPI (4 rules)
│   └── ethernet.py            # Ethernet / high-speed interfaces (10 rules)
├── ui/
│   ├── app.py                 # Curses TUI — layout, animation, run flow
│   ├── file_picker.py         # Directory browser with glob search
│   ├── check_picker.py        # Category-grouped check selector
│   └── results_view.py        # Findings viewer
├── output/
│   ├── log_writer.py          # Plain-text report
│   ├── md_writer.py           # Markdown report
│   └── json_writer.py         # Machine-readable JSON report
├── model.py                   # Netlist · Component · Net · Pin · Finding
├── component_classifier.py    # Refdes + part-number → ComponentType + value
├── confidence.py              # Confidence-based severity downgrade/suppression
└── waivers.py                 # Waiver loading and justified-only suppression
```

---

## Supported File Formats

### Xpedition iCDB XML (`.xml`)

Export via **File → Export → iCDB XML**. The parser handles multiple dialect
variations across Xpedition versions and uses `iterparse` for memory-efficient
processing of large designs. Net constraint classes (`DIFF_PAIR`, `HIGH_SPEED`,
etc.) are parsed when present and stored on `Net.net_constraint_class`.

### HKP Netlist (`.hkp` / `.net` / `.qcv` / `.txt`)

Export via **File → Export → HKP Netlist**. Also accepts PADS-style netlists
(`*PADS-NETLIST*` header), Mentor-style `!COMPONENT_SECTION` / `!NET_SECTION`
format, and Allegro `$PART` / `$NET` format.

---

## Development

```bash
uv sync
uv run ruff check schem_review/
uv run schem_review samples/stm32_eth_test.xml
uv run schem_review samples/stm32_eth_test.xml --verbose
```

---

## Future Roadmap

The following features require external data that cannot be derived from the
schematic alone. They are planned for future releases.

### Datasheet Parser Integration *(planned)*

The highest-impact gap in the current tool is the absence of component
electrical parameters. A datasheet parser (or a curated lookup database) would
enable:

- **VOH/VIL margin computation** — for every signal net, compute
  `VOH(driver) − VIL(receiver)` and flag anything below 200 mV as ERROR.
  Currently `voltage_domain_crossing` uses supply-voltage heuristics with 0.75
  confidence; datasheet data would raise this to a verified CRITICAL.

- **Drive strength budget** — check that the total load current on a net
  (sum of VIL × Rin for all receivers) does not exceed the driver's rated
  `IOH`/`IOL`. Relevant for high-fanout clock nets and open-drain buses.

- **Pin capacitance for crystal / clock nets** — the `crystal_load_caps` check
  currently assumes standard load capacitance. With per-pin capacitance from
  the datasheet, the check can verify that the sum of oscillator pin
  capacitances plus PCB parasitics matches the crystal's specified load.

- **I²C bus capacitance rise-time calculation** — compute
  `t_rise = 0.8473 × R_pull × C_bus` using actual pin capacitances (pF per
  device × number of devices). Currently only the pull-up resistance is
  checked; the full rise-time formula requires datasheet data.

The planned interface: a `--parts-db` argument accepting a JSON file in the
format `{part_number: {voh_min, vol_max, vih_min, vil_max, ioh_ma, iol_ma,
cin_pf, ...}}`. Parts not in the database fall back to heuristics.

### BOM Cross-Reference *(planned)*

Accept a `--bom` CSV/JSON argument. When present:

- Upgrade `voltage_domain_crossing` from heuristic (0.75) to verified (1.0)
  by reading actual supply voltage from the BOM entry.
- Verify that component values in the schematic match the BOM quantity
  (e.g. 100 nF schematic vs. 10 nF BOM).
- Flag BOM-only components (on BOM but not in schematic) and schematic-only
  components (in schematic but not on BOM) as ERROR.

### PCB Constraint Back-Annotation *(planned)*

Accept the Xpedition constraint export (`.xml` constraint file) alongside
the schematic. When present:

- Verify that every `DIFF_PAIR` constraint-class net has a matching P and N
  member with equal series resistance.
- Flag any net in a `HIGH_SPEED` class that routes through a test point or
  high-capacitance component (e.g. a bulk capacitor in series).
- Check that `POWER` constraint-class nets have appropriate copper weight
  annotations (where the schematic carries them).

### Hierarchical Port Direction Mismatch *(planned)*

Multi-sheet designs use hierarchical ports to connect sheets. The parser
currently merges everything into a flat netlist. A future enhancement will
preserve the hierarchical structure and check:

- A port declared as `OUTPUT` on one sheet must not connect to a port declared
  as `OUTPUT` on another sheet (two drivers).
- A port declared as `INPUT` must have exactly one `OUTPUT` source across all
  sheets.
- Bidirectional ports that appear on only one sheet are flagged as orphaned
  hierarchy ports.

### Full Power Sequencing with Timing *(planned)*

The current `power_sequencing` check detects structural problems (cycles, unsequenced enables) but does not verify timing. A future enhancement will:

- Parse RC delay values on EN nets to compute estimated ramp delays.
- Allow user-supplied sequencing constraints in `waivers.toml`:
  `sequence = ["VDD_5V", "VDD_3V3", "VDD_1V8", "VCORE"]` with optional
  `min_delay_ms` between each stage.
- Flag any topology where the inferred order contradicts the constraints.

---

## License

MIT © 2026 redrussian1917
