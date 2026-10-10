# blitzBUS / blitz86 v48 — sampled native dispatch profiler

This is a **diagnostic-only** change. It samples one out of every 256
outer native dispatches and records total time until the native entry
returns. The native entry may chain across multiple translated blocks;
therefore the printed CS:IP is the **entry attribution**, not a direct
PC sample, an exact hot-block ranking, or exclusive execution time.
Hash collisions replace older entries. Treat rankings as candidate sites.

## Install (PowerShell)

```powershell
cd C:\blitzBUS
python .\v48-hotprofile\install_v48.py --blitz86 C:\blitz86_v2 --blitzbus C:\blitzBUS --check
python .\v48-hotprofile\install_v48.py --blitz86 C:\blitz86_v2 --blitzbus C:\blitzBUS --apply
$env:BB_LCD_PERI_HZ = '150000000'
$env:BB_LCD_SPI_HZ = '75000000'
$env:BB_LCD_LACE = '1'
.\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180
```

Run 3DBENCH and send the lines starting `[bb-v48-hot]` and
`[bb-v48-hot-entry]`. Compare 3DBENCH to 35.7 FPS; it could decrease
because of instrumentation. Do not compare with old v36 timings.

## Restore

```powershell
python .\v48-hotprofile\install_v48.py --blitz86 C:\blitz86_v2 --blitzbus C:\blitzBUS --restore
```

This restores exactly three files from `.before_v48` copies.
