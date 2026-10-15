# blitzBUS: MS-DOS 6.22 IPL v1 SD-clock fix

## Finding

Actual Pico log (2026-10-13): `DOS622.IMG` mounts successfully before LCD setup, then the first boot-sector read after LCD initialization reports `disk READ ERROR lba=0 fr=1 bytes=0` and the firmware boots its existing DOS 2 kernel.

The SD driver `bb_sd_boot.c` already calls `spi_set_baudrate(spi1, 12500000u)` in its B: and C: read paths because LCD setup increases `clk_peri` from 48 MHz to 150 MHz. The newly added `bb_sd_dos622_read_sector()` lacked that call. A previously valid hardware SPI1 divisor could therefore make post-LCD SD reads run at roughly 37.5 MHz instead of the intended 12.5 MHz. `FR_DISK_ERR (1)` is consistent with failed SD communication, but the actual board read is not verified until the new firmware runs.

## Change

Replace **only** `C:\blitzBUS\sd_boot\bb_dos622_sd.inc` with the provided full source through the installer. The updated `bb_sd_dos622_read_sector()` retimes **SPI1** before each `f_lseek`/`f_read` and prints actual `old`, `new`, and `peri` clocks for its first two reads. A failed operation now prints `stage=seek` or `stage=read`, plus SPI1 baud.

- No change to `src/bb_live.c`, `b86.h`, `src/interp.c`, 386 code, 286 JIT, SRAM cache, DOS 2 kernel, disk images, or LCD SPI0.
- Installer updates the original IPL v1 SHA manifest for this single created source file so `bb_dos622_ipl_v1.py verify` continues to pass.
- Installer maintains its own original source and original IPL manifest backups for byte-exact rollback.
- The source must match the known IPL-v1 file. Modified/unknown versions are **not** overwritten.

## Install

Extract the ZIP directly into `C:\blitzBUS` (all files at the top level). The replacement `.inc` in the ZIP is **not** intended for manual overwriting in the `sd_boot` directory; the installer handles verification and backups.

```powershell
cd C:\blitzBUS
python .\bb_dos622_ipl_v1.py verify
python .\bb_dos622_sd_clockfix_v1.py selftest
python .\bb_dos622_sd_clockfix_v1.py probe
python .\bb_dos622_sd_clockfix_v1.py apply
python .\bb_dos622_sd_clockfix_v1.py verify
python .\bb_dos622_ipl_v1.py verify
```

**Do not repeat image staging.** Your current DOS622.IMG, DOS622D2.IMG, DOS622D3.IMG and DOS622.TXT on `O:\BLITZBUS` were already staged and verified.

## Reflash

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
$env:BB_LCD_PERI_HZ = '150000000'
$env:BB_LCD_SPI_HZ = '75000000'
$env:BB_LCD_LACE = '1'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180
```

Expected **first diagnostics** (subject to hardware confirmation):

```
[bb-dos622-clockfix] spi1 old=37500000 new=12500000 peri=150000000
[bb-dos622] read lba=0 OK
[bb-dos622] ENTER real boot sector 0000:7C00, BIOS DL=00; image read-only
```

**Important:** After `ENTER`, DOS 6.22 may request other BIOS services or exhibit CPU-boot compatibility problems. The fix only addresses the observed first SD-read error. Do not infer a successful DOS 6.22 kernel boot until a genuine DOS 6.22 prompt appears and `VER` reports 6.22.

## Restore

```powershell
cd C:\blitzBUS
python .\bb_dos622_sd_clockfix_v1.py verify
python .\bb_dos622_sd_clockfix_v1.py restore
python .\bb_dos622_ipl_v1.py verify
```

## Tests run here

- Standalone installer selftest on LF and CRLF; apply/verify/exact-byte rollback PASS.
- Compiled *complete replacement .inc* into a GCC C11 FatFs/SPI mock with `-Wall -Wextra -Werror`: PASS.
- Clang address+undefined sanitizer mock: PASS.
- Mock confirms SPI1 is retimed to 12.5 MHz before FatFs seek/read, validates legal last LBA and rejects sector 2880, reports errors separately for `f_lseek` and `f_read`.
- **Actual Pico hardware results remain unverified.**
