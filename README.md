<div align="center">

<!-- Replace src with your actual logo path once created -->
<!-- <img src="docs/assets/logo.png" alt="schem_review" width="160"/> -->

# schem_review

**Automated schematic linter for Xpedition EDA designs.**

[![Build](https://img.shields.io/badge/build-passing-brightgreen?style=flat-square)](https://github.com/redrussian1917/schem_review/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue?style=flat-square)](https://www.python.org/)
[![Checks: 28 rules](https://img.shields.io/badge/checks-28%20rules-orange?style=flat-square)](#-check-catalog)
[![Input: iCDB XML · HKP](https://img.shields.io/badge/input-iCDB%20XML%20%7C%20HKP-lightgrey?style=flat-square)](#supported-file-formats)

---

**Catch unconnected pins, broken differential pairs, missing MDIO pull-ups, and 25 other design errors in your netlist — before they become a $4,000 PCB respin.**

</div>

---

## 👀 See It in Action

<!-- Record with: terminalizer record demo -- bash -c "schem_review samples/stm32_eth_test.xml" -->
<!-- Then render with: terminalizer render demo -o docs/assets/demo.gif                         -->
<!-- <img src="docs/assets/demo.gif" alt="schem_review terminal demo" width="720"/>             -->

Running against the included sample design surfaces **25 findings** across **7 rule categories** in under a second:

```
$ schem_review samples/stm32_eth_test.xml

schem_review — headless mode
File: samples/stm32_eth_test.xml
Parsed: 21 components, 38 nets, 3 sheets

  Running: unconnected_pins
  Running: floating_inputs
  Running: power_pin_conflicts
  ...
  Running: sgmii_termination

Findings: 25

  [ERROR] unconnected_pins: U1 pin 25 (PC0) is unconnected
  [ERROR] floating_inputs: Net 'UART1_RX' has input pin(s) but no driver
  [WARN]  i2c_signals: I2C net 'I2C2_SDA' has no matching SCL net
  [WARN]  spi_signals: SPI bus 'SPI1' is incomplete — missing: CS
  [WARN]  sgmii_differential_pairs: ETH_TXP has no AC-coupling capacitor
  [WARN]  sgmii_termination: SerDes pair 'ETH_TX' has no termination resistor
  ...

Log:      samples/stm32_eth_test_review_20260412_120000.log
Markdown: samples/stm32_eth_test_review_20260412_120000.md
```

### Detected errors vs. corrections

| Finding | The Fix |
|---|---|
| `[ERROR]` U1 pin 25 (PC0) is unconnected | Connect to a net or add an NC marker |
| `[ERROR]` `UART1_RX` has inputs but no driver | Ensure the driving side (UART TX out) is netted in |
| `[WARN]` `I2C2_SDA` has no matching SCL | Add `I2C2_SCL` or remove the orphan SDA net |
| `[WARN]` SPI1 bus missing CS | Add a chip-select net (`SPI1_CS`) to complete the bus |
| `[WARN]` `ETH_TXP` has no AC-coupling cap | Place a series 100 nF cap on each SerDes lane |
| `[WARN]` SerDes pair has no termination | Add 100 Ω differential or 50 Ω per-side termination |
| `[WARN]` Mixed `REG_EN#` / `N_EN_LED` naming | Standardise on suffix (`#`) or prefix (`N_`) style |
| `[WARN]` `VDD_3V3` mixed with `VCC_3V3` rail | Rename to match the dominant `VCC` convention |

---

## ✨ Key Features

- **Protocol-aware linting** — dedicated rule sets for I²C (pull-up pairing), SPI (bus completeness), UART (TX/RX crossing), SGMII (AC-coupling, DC bias, termination, polarity), RGMII (bus completeness, voltage domain, series resistors), MDI (Bob Smith termination), and MDIO (pull-ups, PHY address conflicts, reset sequencing).

- **Differential pair integrity** — every P-net is matched to its N-net; series AC-coupling caps and DC-bias resistors are verified on SerDes lanes; P/N polarity swaps are flagged at the pin level.

- **Power & ground discipline** — AGND/DGND isolation audit, ferrite bead derating advisory on PHY supply rails, and decoupling capacitor coverage checks on all IC power pins.

- **Design hygiene** — net naming consistency (VCC vs VDD), active-low polarity conventions (EN#, N_EN, /EN), and reset signal ambiguity detection.

- **Fanout & connectivity** — unconnected pins, floating inputs with no driver, and multi-driver power conflicts caught at parse time.

- **Interactive TUI + headless CI mode** — full curses UI with category-grouped check picker (collapsible, live `/` search), animated progress indicator, and Markdown + plain-text report export. Or run headless and let exit code 1 break your CI pipeline on any ERROR.

- **28 rules, zero dependencies** — pure Python standard library. No pip packages required beyond your Python interpreter.

---

## 🚀 Quick Start

```bash
# Install (requires Python ≥ 3.8, recommended: uv)
pip install .
# or: uv tool install .

# Interactive TUI
schem_review

# Headless — run all checks, exit 1 on any ERROR
schem_review path/to/design.xml

# Headless — targeted check subset
schem_review design.xml --checks sgmii_differential_pairs,mdio_pullup,unconnected_pins
```

Output files are written alongside the input automatically:
`design_review_<timestamp>.md` and `design_review_<timestamp>.log`

---

## 🗂 Check Catalog

| Category | # | Checks |
|---|:-:|---|
| **DRC** | 5 | `unconnected_pins` · `floating_inputs` · `power_pin_conflicts` · `missing_decoupling_caps` · `net_naming_consistency` |
| **EE** | 8 | `i2c_signals` · `uart_signals` · `spi_signals` · `differential_pairs` · `power_rail_naming` · `reset_signals` · `enable_signals` · `clock_signals` |
| **SGMII** | 4 | `sgmii_differential_pairs` · `sgmii_dc_bias` · `sgmii_termination` · `sgmii_polarity_swap` |
| **RGMII** | 3 | `rgmii_bus_completeness` · `rgmii_series_termination` · `rgmii_voltage_domain` |
| **MDI** | 3 | `mdi_bob_smith_termination` · `mdi_pair_association` · `ethernet_led_current` |
| **MDIO** | 3 | `mdio_pullup` · `phy_address_conflict` · `phy_reset_sequencing` |
| **PWR** | 2 | `agnd_dgnd_isolation` · `ferrite_bead_derating` |

In the TUI **Checks** tab, type `/sgmii` to instantly filter to SGMII rules, or `/term` to find all termination checks across categories.

---

## 📖 UI Reference

```
┌──────────────────────────────────────────────────────────────────────────┐
│ schem_review v0.1                              [F1]Help  [R]Run  [Q]Quit │
├──────────────────┬──────────────────┬──────────────────┬─────────────────┤
│  1:Files         │  2:Checks        │  3:Results       │   [ RUN ]       │
├──────────────────┴──────────────────┴──────────────────┴─────────────────┤
│                                                                           │
│  (active panel)                                                           │
│                                                                           │
├───────────────────────────────────────────────────────────────────────────┤
│ design.xml  |  28 checks selected  |  Step 1: select a file …            │
└───────────────────────────────────────────────────────────────────────────┘
```

### Global keys

| Key | Action |
|---|---|
| `1` `2` `3` | Jump to Files / Checks / Results tab |
| `Tab` / `←` `→` | Cycle tabs |
| `R` | Run selected checks on the loaded file |
| `F1` | Keyboard shortcut help overlay |
| `Q` | Quit |

### Tab 1 — Files

Navigate the filesystem to your `.xml` or `.hkp` file.

| Key | Action |
|---|---|
| `↑` `↓` | Move cursor |
| `→` or `↵` | Enter directory / select file |
| `←` or `⌫` | Go up to parent directory |
| `/` | Live filter by filename |
| `PgUp` `PgDn` | Fast scroll |

### Tab 2 — Checks

Enable or disable checks, grouped by category.

| Key | Action |
|---|---|
| `↑` `↓` | Move cursor |
| `Space` or `↵` | Toggle check on/off; collapse/expand category |
| `A` | Enable all (filtered) checks |
| `N` | Disable all (filtered) checks |
| `/` | Filter checks by name, description, or category |
| `Esc` | Clear filter |

### Tab 3 — Results

Findings grouped by severity (ERROR → WARN → INFO).

| Key | Action |
|---|---|
| `↑` `↓` | Move cursor |
| `↵` | Expand finding detail / collapse severity section |
| `/` | Search: `error\|warn`, `net&open`, `power*flag` |
| `Esc` | Clear search |
| `PgUp` `PgDn` | Fast scroll |

Search syntax: `|` = OR, `&` = AND, `*` = wildcard.

---

## 📐 Project Layout

```
schem_review/
├── parser/
│   ├── xml_parser.py      # iCDB XML → Netlist
│   └── hkp_parser.py      # Xpedition HKP / PADS / Allegro → Netlist
├── checks/
│   ├── registry.py        # @register decorator and check runner
│   ├── drc.py             # Structural DRC (5 rules)
│   ├── ee.py              # EE conventions (8 rules)
│   └── ethernet.py        # Ethernet / high-speed interfaces (15 rules)
├── ui/
│   ├── app.py             # Curses TUI — layout, animation, run flow
│   ├── file_picker.py     # Directory browser with live search
│   ├── check_picker.py    # Category-grouped check selector with search
│   └── results_view.py    # Findings viewer with OR/AND/wildcard search
├── output/
│   ├── log_writer.py      # Plain-text report
│   └── md_writer.py       # Markdown report
├── model.py               # Netlist · Component · Net · Pin · Finding
└── samples/
    ├── sample_design.xml       # Basic DRC/EE exercise file
    └── stm32_eth_test.xml      # STM32 + Ethernet — exercises all 28 rules
```

---

## ➕ Adding a Custom Check

Drop a decorated function into any `checks/*.py` file — it is auto-discovered at import time:

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

Then register the import in `schem_review/checks/__init__.py`:

```python
from schem_review.checks import drc, ee, ethernet, my_checks  # noqa: F401
```

The check appears automatically in the TUI and headless mode — no other changes required.

---

## Supported File Formats

### Xpedition iCDB XML (`.xml`)

Export via **File → Export → iCDB XML**. The parser handles multiple dialect
variations across Xpedition versions and uses `iterparse` for memory-efficient
processing of large designs.

### HKP Netlist (`.hkp` / `.net`)

Export via **File → Export → HKP Netlist**. Also accepts PADS-style netlists
(`*PADS-NETLIST*` header), Mentor-style `!COMPONENT_SECTION` / `!NET_SECTION`
format, and Allegro `$PART` / `$NET` format.

---

## Development

```bash
# Install dev tools
uv sync

# Lint
uv run ruff check schem_review/

# Run headless on the sample file
uv run schem_review samples/stm32_eth_test.xml
```

---

## License

MIT © 2026 redrussian1917

---

<div align="center">

For full design rule specifications and parser format documentation, see
**[docs/technical_details.md](./docs/technical_details.md)**

</div>
