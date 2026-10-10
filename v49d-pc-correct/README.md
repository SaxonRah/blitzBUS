# v49d — corrected SysTick PC sampling

Replaces only `C:\blitzBUS\src\bb_v49_pc.h` from the exact v49c probe version. No changes to blitz86, JIT, or DOS logic.

The captured EXC_RETURN `FFFFFFE9` has bit 4 set, meaning the **basic** core exception frame. v49b incorrectly jumped to word 24 (`+72` bytes, then PC at `+24`) for this form, reading unrelated guest data. v49d uses the 8-word frame directly when bit 4 is set and skips 18 words only when it is clear (extended frame). An xPSR Thumb-bit check rejects implausible candidates. Exception handler does not print or allocate memory. The existing 1024-sample ring and JIT block mapping are retained.

## Install

```powershell
cd C:\blitzBUS
python .\v49d-pc-correct\install_v49d.py --blitzbus C:\blitzBUS --check
python .\v49d-pc-correct\install_v49d.py --blitzbus C:\blitzBUS --apply
$env:BB_LCD_PERI_HZ = '150000000'
$env:BB_LCD_SPI_HZ = '75000000'
$env:BB_LCD_LACE = '1'
.\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180
```

Run `3DBENCH` and capture stats while it is rendering. Expected prefixes: `[bb-v49d-state]`, `[bb-v49d-regions]`, `[bb-v49d-rawpc]`, `[bb-v49-pc-block]`. Some recorded samples may still be classified outside translated blocks; this is not necessarily a bug, since native support functions execute too. Samples are interval-based, and stale-code PC mapping after a cache flush remains a limitation.

## Rollback

```powershell
python .\v49d-pc-correct\install_v49d.py --blitzbus C:\blitzBUS --restore
```

## Verification

Installer round-trip, Python syntax, and ZIP integrity have been tested locally. Cross-compilation and behavior on RP2350 are not tested in this environment. Preserve a known-good firmware image in case the experimental exception sampler has unexpected behavior.
