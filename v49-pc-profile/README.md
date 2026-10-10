# blitzBUS + blitz86 v49 — experimental interrupt-PC profiler

This opt-in experiment **does not replace v48**. Backups are made of the 3 edited source files. The patched `bb_live.c` enables v49 through `BB_V49_PC_PROFILE`.

## Why SysTick?

The v48 profiler timed native dispatch entries, missing chained blocks. v49 samples the **interrupted Cortex-M33 PC** at 1 kHz with a dedicated SysTick exception handler, then maps those host addresses to live blocks outside the handler. The handler only writes raw PCs to a 1024-slot ring. It does not inspect guest state or translate anything.

**Important:** the 1024-slot ring represents up to ~1 second of recent PC samples; reports are *interval* profiles, not accumulated profiles. Older samples are overwritten, and the output states how many. JIT metadata may be flushed before a sample is analyzed, so some PCs cannot be mapped. PC-to-block resolution, not guest-instruction resolution, is the supported level of precision. Interrupts landing outside generated code count as `outside-jit`.

**Safety:** v49 refuses to use SysTick if it is already active, if VTOR isn't in the RP2350 internal writable SRAM region, if its handler vector already points within that SRAM region, or if the reload is invalid. If disabled, normal DOS behavior continues; the logs say why. The profiler is enabled on core 0 only, after successful JIT creation. It does not affect the DOS PIT or PIC.

## Installation

Extract ZIP to `C:\blitzBUS\v49-pc-profile`, then:

```powershell
cd C:\blitzBUS
python .\v49-pc-profile\install_v49.py --blitz86 C:\blitz86_v2 --blitzbus C:\blitzBUS --check
python .\v49-pc-profile\install_v49.py --blitz86 C:\blitz86_v2 --blitzbus C:\blitzBUS --apply
```

Build with the unchanged command:

```powershell
$env:BB_LCD_PERI_HZ = '150000000'
$env:BB_LCD_SPI_HZ = '75000000'
$env:BB_LCD_LACE = '1'
.\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180
```

Run `3DBENCH`, capture `[bb-v49-pc]` and `[bb-v49-pc-block]`. The sample window may be sparse if statistics are requested very rapidly. Use the normal Ctrl+] report during rendering to get the last ~second's ranking.

## Rollback

```powershell
python .\v49-pc-profile\install_v49.py --blitz86 C:\blitz86_v2 --blitzbus C:\blitzBUS --restore
```

This is **experimental**. The Pico cross-build and execution have not been run in this environment. The installer passed local source-anchor/syntax testing only. If SysTick is claimed by other firmware, it must skip installation; do not force replacement of another handler.
