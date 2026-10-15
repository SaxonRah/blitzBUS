# blitzBUS DOS 6.22 boot diagnostic v1

## Reason for this build

After installing the DOS622 SPI1 clock fix, the Pico linked and flashed successfully (RAM 522,492 / 524,288 B; 99.66%), but the PowerShell console reported:

```
[bb-dos622] DOS622.IMG boot candidate mounted A: 1440KiB READ-ONLY (opt-in)
...
keys: Ctrl+] -> tier/native statistics (boot + interval)
[blitzBUS] FAIL: Exception calling "ReadExisting" with "0" argument(s): "The port is closed."
```

This is a **serial-port closure**, not proof of either a new FatFs error or a firmware hard fault. The original SPI1 fix still hasn't emitted its `spi1 old=... new=...` line, so it has not been observed executing. This diagnostic instruments the steps between the last logged banner and the DOS6 first-sector load.

## What this changes

- Adds **16 flushed, numbered checkpoints** to `src/bb_live.c` (boot startup) and `src/bb_dos622_bios.inc` (boot sector load).
- Changes **no guest instructions**, 386 code, clockfix code, 286 JIT, ROM image, USB firmware, or code-cache size.
- Updates `C:\blitzBUS\.bb_dos622_ipl_v1_state\manifest.json` to keep `bb_dos622_ipl_v1.py verify` valid. Keeps the exact prediagnostic source bytes and manifest for reversal.
- No direct edits to the existing `DOS622.IMG`, `BOOT.IMG`, or `DRIVE_C.IMG`.
- New code is cold-startup `printf`/`fflush`, not the native fast path. **A Pico SRAM linker check is still required.**

## Install full file

Extract `bb_dos622_boot_diag_v1.py` into `C:\blitzBUS`. The current IPL v1 and clockfix must already be installed. Run:

```powershell
cd C:\blitzBUS
python .\bb_dos622_sd_clockfix_v1.py verify
python .\bb_dos622_ipl_v1.py verify
python .\bb_dos622_boot_diag_v1.py selftest
python .\bb_dos622_boot_diag_v1.py probe
python .\bb_dos622_boot_diag_v1.py apply
python .\bb_dos622_boot_diag_v1.py verify
python .\bb_dos622_ipl_v1.py verify
```

Do not rerun IPL `apply`; it is already installed. An exact-anchor mismatch is intentional protection, not a reason to force-replace source files.

## Rebuild and capture

```powershell
cd C:\blitzBUS
$env:BB_CPU = '286'
$env:BB_CODE_KB = '232'
$env:BB_HOT_THRESHOLD = '32'
$env:BB_EVICT_CHUNK = '4096'
$env:BB_EVICT_ROOM = '2048'
$env:BB_NO_CHAIN = '0'
$env:BB_BBUF = '1'
$env:BB_SD_BOOT = '1'

powershell -NoProfile -ExecutionPolicy Bypass `
    -File .\scripts\bb_live_run.ps1 `
    -MicroDOS C:\microDOS `
    -Blitz86 C:\blitz86_v2 `
    -Port COM5 `
    -Seconds 180
```

## How to interpret the checkpoints

| Last message | Interpretation |
| --- | --- |
| `keys:` banner, no `01 start.enter` | The startup callback was not reached, or USB disconnected before the checkpoint was sent. Check whether COM5 reappears; on next boot inspect previous-run hardfault diagnostic. |
| `02 before.b86_init`, no `03` | Investigate `b86_init` and PSRAM. |
| `04 before.386_probe`, no `05` | Investigate the isolated 386 test/PSRAM. |
| `07 before.jit_create`, no `08` | Investigate JIT creation/cache metadata allocation. |
| `10 before.dos622_boot` then `12 before.sector0`, no `14` | Check the SD SPI1 retime log and FatFs status; a disconnect during read differs from a reported read failure. |
| `13 sector0.FAILED` | The sector reader returned failure and should also log the FatFs stage and result. |
| `14 sector0.OK`, then no `16` | Inspect boot-sector copy and microDOS guest-memory mapping. |
| `16 after.copy_boot_sector`, followed by `ENTER` | IPL loaded; further problems lie in real boot-sector execution/BIOS compatibility. |

If Windows reports "The port is closed", check whether the Pico reappears on COM5 or a different port. The host PowerShell script closing its serial object can also produce this error. **One such report alone is not proof of a hardfault.** The existing firmware may report `PREVIOUS RUN HARDFAULT` at the following startup if it detected one.

## Control experiment (does not modify the SD image)

If the disconnect repeats, temporarily disable DOS6 in the selector **on the actual SD drive** (previously `O:`), then reboot using the same UF2:

```powershell
[System.IO.File]::WriteAllText('O:\BLITZBUS\DOS622.TXT', '0')
```

When done, restore the selector:

```powershell
[System.IO.File]::WriteAllText('O:\BLITZBUS\DOS622.TXT', '1')
```

If DOS2 boots consistently with the same diagnostic firmware and `DOS622.TXT=0`, that helps isolate the opt-in DOS6 path. This selector changes which disk is booted; it does not claim to identify an exact function-level failure.

## Restore diagnostic only

```powershell
cd C:\blitzBUS
python .\bb_dos622_boot_diag_v1.py verify
python .\bb_dos622_boot_diag_v1.py restore
python .\bb_dos622_ipl_v1.py verify
python .\bb_dos622_sd_clockfix_v1.py verify
```

The diagnostic restore returns both edited files and the original IPL manifest **byte-for-byte**, leaving PM0 and the SD clockfix installed.

## Status

The installer was tested in self-contained LF and CRLF environments, including SHA checks and exact restoration. The emitted code is only trace statements, but the user's complete Pico build, boot result, and SRAM capacity are **not yet verified**. Share the next COM capture, including the first `[bb622-diag]` entry and any `[bb-dos622-clockfix]` or `PREVIOUS RUN HARDFAULT` messages.
