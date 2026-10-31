# blitzBUS

blitzBUS runs DOS on a Pimoroni Pico Plus 2 (RP2350): the microDOS firmware, the
blitz86 x86 core, an SPI LCD, and SD-card disk images. This repository holds the
board glue (`src/`, `sd_boot/`), the build/run scripts, and the DOS test media.

It works together with two sibling checkouts:

| Checkout | Default path | Setting |
|---|---|---|
| microDOS (firmware build tree) | `C:\microDOS` | `BB_MICRODOS` |
| blitz86 (CPU core) | `C:\blitz86_v2` | `BB_BLITZ86` |

## Commands

Everything starts from `bb.bat`:

```powershell
cd C:\blitzBUS
.\bb.bat boot                     # DOS 6.22: install, build, flash, console
.\bb.bat boot -ConsoleView Raw    # same, raw console view
.\bb.bat build                    # DOS 6.22: build the firmware only
.\bb.bat run                      # DOS 2 firmware (original runner)
.\bb.bat run -BuildOnly           # DOS 2: build only
.\bb.bat install                  # add the LCD console overlay to microDOS
.\bb.bat restore                  # remove that overlay
.\bb.bat config                   # show every setting and where it comes from
.\bb.bat log                      # latest console log and its key counters
.\bb.bat report                   # PC-sample report for the latest log
.\bb.bat help
```

| Command | Options and notes |
|---|---|
| `boot` | `-NoBuild`, `-NoFlash`, `-NoInput`, `-Seconds N`, `-ConsoleView Screen\|Events\|Raw`, `-Port COMx`, `-AutoTests`, `-PhaseProfile`. In the console, Ctrl+] requests blitz86 counters and Ctrl+X exits. The old spelling `bb dos boot` still works. |
| `build` | Writes the firmware to `C:\microDOS\build-pico\out\blitzbus_pico_b86_dos.uf2`. |
| `run` | `-BuildOnly`, `-Seconds N`, `-Port COMx`. |

While `bb boot` is running, use a second window for:

```powershell
.\bb.bat disk B 3     # swap the floppy in B: to Descent disk 3 (waits for the firmware ACK)
.\bb.bat irq0         # arm the IRQ0 one-shot trial (docs\experiments\IRQ0_ONE_SHOT_TRIAL_V1.md)
.\bb.bat pic          # toggle the PIC probe
```

## Settings

All build and run settings live in **`bb.config.psd1`**. These are the values of
the last known-good firmware. With them, `scripts\install_live.py` writes exactly
the `BB_*` block that was in microDOS `pico\CMakeLists.txt`, so every fresh window
builds the same firmware.

A variable that is already set in the window wins, so a one-off experiment needs
no edit:

```powershell
$env:BB_PJ_HOT_KB = '128'; .\bb.bat boot
```

`bb boot` and `bb build` print any window overrides before they start, and
`bb config` lists every value with its source.

| Setting | Known-good | Meaning |
|---|---|---|
| `BB_MICRODOS`, `BB_BLITZ86`, `BB_PORT` | `C:\microDOS`, `C:\blitz86_v2`, `COM5` | checkouts and serial port |
| `BB_SD_BOOT` | `1` | boot DOS 6.22 from the SD-card images |
| `BB_CPU` | `386` | `8086`, `186`, `286` or `386` |
| `BB_386_NATIVE_T1` | `1` | native 386 tier 1 (needs `BB_CPU=386`) |
| `BB_PAGED` | `1` | paged guest memory |
| `BB_GUEST_KB` | `4096` | guest RAM |
| `BB_CODE_KB` | `128` | real-mode JIT code cache |
| `BB_BBUF` | `0` | block buffer in SRAM |
| `BB_PM_IRQ0` | `0` | keep 0, because continuous protected-mode IRQ0 delivery is unsafe |
| `BB_PM_KBD`, `BB_PM_RAM` | `1`, `1` | protected-mode keyboard IRQ; PM hot paths in SRAM |
| `BB_PJ`, `BB_PJ_PSRAM` | `1`, `1` | protected-mode JIT; code cache in PSRAM |
| `BB_PJ_CODE_KB`, `BB_PJ_HOT_KB` | `1024`, `96` | PSRAM code cache; SRAM hot tier |
| `BB_PC_PROFILE` | `1` | PC-sampler lines in the console log |
| `BB_LCD_SPI_HZ`, `BB_LCD_PERI_HZ`, `BB_LCD_LACE` | `75000000`, `150000000`, `1` | LCD SPI clock, peripheral clock, interlaced strips |

`scripts\install_live.py` also reads rarely used tuning variables. If one isn't
set, it keeps its own default. These are `BB_NO_CHAIN`, `BB_HOT_THRESHOLD`,
`BB_EVICT_CHUNK`, `BB_EVICT_ROOM`, `BB_MISS_PROFILE`, `BB_TV_SRAM`,
`BB_PIN_PAGES`, `BB_META_KB`, `BB_PJ_MAXI`, `BB_PJ_CHAIN` and `BB_VREG_MV`.

## Layout

| Path | Contents |
|---|---|
| `bb.bat`, `bb.config.psd1` | entry point and settings |
| `scripts\bb.ps1` | command dispatcher |
| `scripts\bb_live_run.ps1` | DOS 6.22 runner: build, flash, serial console, second-window requests |
| `scripts\bb622_descent_color_host.ps1` | Screen/Events console view used by the runner |
| `scripts\install_live.py` | writes the live target into microDOS `pico\CMakeLists.txt` and `generated\` |
| `scripts\bb_run.ps1`, `scripts\install_overlay.py` | DOS 2 runner; LCD overlay install/restore |
| `scripts\bb622_request_media.ps1`, `scripts\bb622_irq0_trial.ps1`, `scripts\bb622_pic_toggle.ps1` | second-window helpers |
| `scripts\bb_pc_report.ps1` | PC-sample report |
| `src\`, `sd_boot\` | firmware sources |
| `tools\fat16tool.py`, `tools\sdtools.py` | FAT16 and SD-card image tools (`tools\*.md`) |
| `dos_bench\`, `media\` | DOS benchmarks and the 3DBench image |
| `games\` | Descent install disks |
| `blitzOverview\` | project overview images |

`generated\` and `logs\` are created locally and are not tracked. DOS disk images
(`*.IMG`) and logs are never touched by any script here.
