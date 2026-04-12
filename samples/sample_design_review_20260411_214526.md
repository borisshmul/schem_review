# schem_review Report

**Source:** `/Users/borisshmul/Documents/xpedition_autos/schem_review/samples/sample_design.xml`  
**Generated:** 2026-04-11T21:45:26  
**Total findings:** 4

## Summary

| Check | ERROR | WARN | INFO |
|-------|------:|-----:|-----:|
| `clock_signals` | 0 | 1 | 0 |
| `differential_pairs` | 0 | 1 | 0 |
| `enable_signals` | 0 | 1 | 0 |
| `power_rail_naming` | 0 | 1 | 0 |

## WARN (4)

### `clock_signals` — 1 finding(s)

- **Differential clock 'MCLK_P' has P side but no N side**
  - Affected: `MCLK_P`

### `differential_pairs` — 1 finding(s)

- **Differential pair 'MCLK' has P side ('MCLK_P') but no N side**
  - Affected: `MCLK_P`

### `enable_signals` — 1 finding(s)

- **Inconsistent active-low enable naming: suffix style (REG_EN#) mixed with prefix style (N_EN_LED)**
  - Affected: `N_EN_LED, REG_EN#`

### `power_rail_naming` — 1 finding(s)

- **Mixed power rail style: design uses mostly 'VCC' convention but also has: VDD_3V3**
  - Affected: `VDD_3V3`

