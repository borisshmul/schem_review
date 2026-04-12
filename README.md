# schem_review

A terminal-based schematic review tool for **Xpedition** designs.
Parses iCDB XML exports and HKP netlists, runs structural DRC and EE-convention
checks, and writes plain-text + Markdown reports — all with zero runtime
dependencies beyond the Python standard library.

---

## Installation

Requires Python ≥ 3.8 and [`uv`](https://github.com/astral-sh/uv).

```bash
cd schem_review
uv sync                 # install dev deps (ruff)
uv run schem_review     # launch interactive UI
```

To install globally so the `schem_review` command is on your PATH:

```bash
uv tool install .
schem_review
```

---

## Quick Start

### Interactive UI (recommended)

```bash
uv run schem_review
```

1. **Tab 1 — Files**: Navigate to your `.xml` or `.hkp` file and press **↵** to select it.
2. **Tab 2 — Checks**: Toggle individual checks on/off with **Space**.
3. Press **[ RUN ]** (or **R** from any tab) to run the review.
4. **Tab 3 — Results**: Browse findings, expand details, collapse sections.

Output files (`.log` and `.md`) are written next to the input file automatically.

### Headless / CI mode

```bash
# Run all checks, exit code 1 if any ERRORs
uv run schem_review path/to/design.xml

# Run a specific subset of checks
uv run schem_review design.hkp --checks floating_inputs,i2c_signals,spi_signals
```

---

## UI Reference

```
┌──────────────────────────────────────────────────────────────────────────┐
│ schem_review v0.1                              [F1]Help  [R]Run  [Q]Quit │  ← header
├──────────────────┬───────────────────┬─────────────────┬────────────────┤
│  1:Files         │  2:Checks         │  3:Results      │   [ RUN ]      │  ← tab bar
├──────────────────┴───────────────────┴─────────────────┴────────────────┤
│                                                                          │
│   (active panel content)                                                 │
│                                                                          │
├──────────────────────────────────────────────────────────────────────────┤
│ File: design.xml | 13 checks selected | Step 1: pick a file …           │  ← status
└──────────────────────────────────────────────────────────────────────────┘
```

### Global keys (work from any tab)

| Key | Action |
|-----|--------|
| `1` `2` `3` | Jump to Files / Checks / Results tab |
| `Tab` | Cycle through all tabs including the **[ RUN ]** button |
| `←` `→` | Previous / next tab (in Files tab: navigate directory) |
| `R` | Run selected checks on the loaded file |
| `↵` on `[ RUN ]` | Same as R — runs the review |
| `F1` | Show keyboard shortcut help |
| `Q` | Quit |

### Tab 1 — Files

Browse the filesystem to select a `.xml` or `.hkp` schematic file.

| Key | Action |
|-----|--------|
| `↑` `↓` | Move cursor |
| `→` or `↵` | Enter directory / select file |
| `←` or `⌫` | Go up to parent directory |
| `PgUp` `PgDn` | Scroll quickly |

Only `.xml` and `.hkp` files can be selected. Other file types are shown
dimmed.

### Tab 2 — Checks

Enable or disable individual checks before running.

| Key | Action |
|-----|--------|
| `↑` `↓` | Move cursor |
| `Space` | Toggle selected check on / off |
| `A` | Select **all** checks |
| `N` | Deselect **all** checks |
| `R` | Run with currently enabled checks |

The **[ RUN ]** button in the tab bar turns green when a file is selected
and at least one check is enabled. Navigate to it with `Tab` or `→` and
press `↵`, or just press `R` from anywhere.

### Tab 3 — Results

Findings are grouped by severity (ERROR → WARN → INFO).

| Key | Action |
|-----|--------|
| `↑` `↓` | Move cursor |
| `↵` | Collapse / expand severity section; expand finding detail |
| `PgUp` `PgDn` | Scroll quickly |

Each finding shows the check name, message, and affected component / net
references. Press `↵` on a finding to reveal the full affected list and
sheet name.

---

## Supported File Formats

### Xpedition iCDB XML (`.xml`)

Export from Xpedition via **File → Export → iCDB XML**. The parser handles
multiple XML dialect variations (different tag names and attribute naming
conventions across Xpedition versions) and uses `iterparse` for efficient
processing of large designs.

### HKP Netlist (`.hkp`)

Export from Xpedition via **File → Export → HKP Netlist**. Also accepts
PADS-style netlists (`.net`) with `*PADS-NETLIST*` headers, Mentor-style
`!COMPONENT_SECTION` / `!NET_SECTION` format, and Allegro `$PART`/`$NET`
format.

---

## Checks

### DRC Checks (structural)

| Check name | Severity | Description |
|---|---|---|
| `unconnected_pins` | ERROR | Component pins with no net connection drawn |
| `floating_inputs` | ERROR | Input pins whose net has no driving output, PWR, or BIDIR pin |
| `power_pin_conflicts` | ERROR | Nets with PWR-type pins from more than one component (multiple power sources) |
| `missing_decoupling_caps` | WARN | ICs (U*) whose power pins have no decoupling capacitor (C* bridging power→GND) |
| `net_naming_consistency` | WARN | Nets that normalize to the same identifier but use different names (e.g. `VCC_3V3` vs `VDD_3V3`) |

### EE Convention Checks

| Check name | Severity | Description |
|---|---|---|
| `i2c_signals` | WARN | I2C SDA/SCL pairing by bus suffix; missing pull-up resistors to power |
| `uart_signals` | WARN | UART TX/RX pairing; TX nets connected only to TX-named pins (crossed connection check) |
| `spi_signals` | WARN | SPI bus completeness — flags buses missing MOSI, MISO, SCK, or CS/NSS |
| `differential_pairs` | WARN | Nets with `_P`/`+` suffix that have no matching `_N`/`−` net, and vice versa |
| `power_rail_naming` | WARN | Detects mixed VCC/VDD rail naming conventions within the same design |
| `reset_signals` | WARN | Flags ambiguous reset net polarity; inconsistent `NRST` / `RST_B` / `RST#` styles across the design |
| `enable_signals` | WARN | Mixed active-low enable naming: suffix style (`EN#`) vs prefix style (`N_EN`) |
| `clock_signals` | WARN | Differential clock nets (`CLK_P`) missing their pair (`CLK_N`) |

---

## Output Files

After each run, two files are written next to the input file:

### Log file — `<stem>_review_<timestamp>.log`

Plain text, one finding per line:

```
[ERROR] unconnected_pins | U1 pin 25 (PC0) is unconnected | affected: U1
[WARN] spi_signals | SPI bus 'SPI1' is incomplete — missing: CS | affected: SPI1_MOSI, SPI1_MISO, SPI1_SCK
```

### Markdown report — `<stem>_review_<timestamp>.md`

Structured report with:
- Summary table: check name × ERROR / WARN / INFO counts
- Findings grouped by severity, then by check
- Affected components and sheet name for each finding

---

## Sample File

A sample design is included at `samples/sample_design.xml`. It intentionally
contains a mix of correct wiring and deliberate issues to exercise all 13
checks:

| Issue | Expected finding |
|-------|-----------------|
| U1 pin 25 (PC0) has no net | `unconnected_pins` ERROR |
| `BTN`, `UART1_RX`, `SPI1_MISO` etc. have no driver | `floating_inputs` ERROR |
| U5 regulator output has no decoupling cap | `missing_decoupling_caps` WARN |
| `VCC_3V3` and `VDD_3V3` both appear | `net_naming_consistency` WARN |
| `I2C2_SDA` present, `I2C2_SCL` missing | `i2c_signals` WARN |
| `UART2_TX` present, `UART2_RX` missing | `uart_signals` WARN |
| `SPI1` has no CS net | `spi_signals` WARN |
| `MCLK_P` clock present, `MCLK_N` missing | `differential_pairs` + `clock_signals` WARN |
| `REG_EN#` (hash style) + `N_EN_LED` (prefix style) | `enable_signals` WARN |

Run it with:

```bash
uv run schem_review samples/sample_design.xml
```

---

## Adding New Checks

Create a new file under `schem_review/checks/` and decorate your function:

```python
# schem_review/checks/my_checks.py
from schem_review.checks.registry import register
from schem_review.model import Finding, Netlist, Severity

@register("Check that all connectors have a mating part number", category="EE")
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

Then import it in `schem_review/checks/__init__.py`:

```python
from schem_review.checks import drc, ee, my_checks  # noqa: F401
```

The check appears automatically in the UI on the next launch — no other
changes needed.

---

## Development

```bash
# Lint and format
uv run ruff check schem_review/
uv run ruff format schem_review/

# Run headless on the sample file
uv run schem_review samples/sample_design.xml
```
