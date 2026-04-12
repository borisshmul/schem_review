# schem_review Report

**Source:** `samples/sample_design.xml`  
**Generated:** 2026-04-11T21:13:41  
**Total findings:** 22

## Summary

| Check | ERROR | WARN | INFO |
|-------|------:|-----:|-----:|
| `clock_signals` | 0 | 1 | 0 |
| `differential_pairs` | 0 | 1 | 0 |
| `enable_signals` | 0 | 1 | 0 |
| `floating_inputs` | 9 | 0 | 0 |
| `i2c_signals` | 0 | 2 | 0 |
| `missing_decoupling_caps` | 0 | 2 | 0 |
| `power_pin_conflicts` | 2 | 0 | 0 |
| `power_rail_naming` | 0 | 1 | 0 |
| `spi_signals` | 0 | 1 | 0 |
| `uart_signals` | 0 | 1 | 0 |
| `unconnected_pins` | 1 | 0 | 0 |

## ERROR (12)

### `floating_inputs` — 9 finding(s)

- **Net 'UART1_RX' has input pin(s) but no driver (no OUT/PWR/BIDIR pin)**
  - Affected: `U1`
  - Sheet: `MCU_Power`
- **Net 'NRST' has input pin(s) but no driver (no OUT/PWR/BIDIR pin)**
  - Affected: `U1`
  - Sheet: `MCU_Power`
- **Net 'BOOT0_EN' has input pin(s) but no driver (no OUT/PWR/BIDIR pin)**
  - Affected: `U1`
  - Sheet: `MCU_Power`
- **Net 'MCLK_P' has input pin(s) but no driver (no OUT/PWR/BIDIR pin)**
  - Affected: `U1, U4`
  - Sheet: `MCU_Power`
- **Net 'REG_EN#' has input pin(s) but no driver (no OUT/PWR/BIDIR pin)**
  - Affected: `U5`
  - Sheet: `MCU_Power`
- **Net 'REG_FB' has input pin(s) but no driver (no OUT/PWR/BIDIR pin)**
  - Affected: `U5`
  - Sheet: `MCU_Power`
- **Net 'LED_BLANK' has input pin(s) but no driver (no OUT/PWR/BIDIR pin)**
  - Affected: `U2`
  - Sheet: `Peripherals`
- **Net 'LED_XLAT' has input pin(s) but no driver (no OUT/PWR/BIDIR pin)**
  - Affected: `U2`
  - Sheet: `Peripherals`
- **Net 'N_EN_LED' has input pin(s) but no driver (no OUT/PWR/BIDIR pin)**
  - Affected: `U6`
  - Sheet: `Peripherals`

### `power_pin_conflicts` — 2 finding(s)

- **Net 'VCC_3V3' has multiple PWR-type pins from: U1, U2, U3, U4, U5, U6**
  - Affected: `U1, U2, U3, U4, U5, U6`
- **Net 'GND' has multiple PWR-type pins from: U1, U2, U3, U4, U5, U6**
  - Affected: `U1, U2, U3, U4, U5, U6`

### `unconnected_pins` — 1 finding(s)

- **U1 pin 25 (PC0) is unconnected**
  - Affected: `U1`
  - Sheet: `MCU_Power`

## WARN (10)

### `clock_signals` — 1 finding(s)

- **Differential clock 'MCLK_P' has P side but no N side**
  - Affected: `MCLK_P`

### `differential_pairs` — 1 finding(s)

- **Differential pair 'MCLK' has P side ('MCLK_P') but no N side**
  - Affected: `MCLK_P`

### `enable_signals` — 1 finding(s)

- **Inconsistent active-low enable naming: suffix style (REG_EN#) mixed with prefix style (N_EN_LED)**
  - Affected: `N_EN_LED, REG_EN#`

### `i2c_signals` — 2 finding(s)

- **I2C net 'I2C2_SDA' has no matching SCL net**
  - Affected: `I2C2_SDA`
- **I2C net 'I2C2_SDA' has no pull-up resistor to a power net**
  - Affected: `I2C2_SDA`

### `missing_decoupling_caps` — 2 finding(s)

- **U5 (TPS62130) has no decoupling cap on power net 'VCC_5V'**
  - Affected: `U5`
  - Sheet: `MCU_Power`
- **U6 (TPS22919) has no decoupling cap on power net 'VCC_LED'**
  - Affected: `U6`
  - Sheet: `Peripherals`

### `power_rail_naming` — 1 finding(s)

- **Mixed power rail style: design uses mostly 'VCC' convention but also has: VDD_3V3**
  - Affected: `VDD_3V3`

### `spi_signals` — 1 finding(s)

- **SPI bus 'SPI1' is incomplete — missing: CS**
  - Affected: `SPI1_MOSI, SPI1_MISO, SPI1_SCK`

### `uart_signals` — 1 finding(s)

- **UART net 'UART2_TX' has no matching RX net**
  - Affected: `UART2_TX`

