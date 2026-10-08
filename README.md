# blitzBUS v0.3 — Pico LCD startup fix

The v0.2 run showed 100% verified flashing and opening COM5, but stalled
immediately after `guest: 1024 KiB...`. The next C statement is `bb_lcd_console_init()`.
The LCD state was zero-initialized (NULL `spi`, GPIO 0), while MicroRender
`mr_pico_ili9341_init()` uses those fields immediately. v0.3 supplies the
identical initializer used by the working MicroConsole FastDoom Pico target.

## Install

Extract these full replacement files **over** `C:\blitzBUS`, retaining the backups
and any other files already in your repository. Then:

```powershell
cd C:\blitzBUS
.\bb.bat upgrade
.\bb.bat run -Port COM5 -Seconds 180 -AutoDos2Test
```

The upgrade changes only `C:\microDOS\blitzbus-overlay\bb_lcd_console.c`.
It does not reapply v0.2 or overwrite your original microDOS files.

## Expected serial checkpoints

```
[blitzBUS] LCD SPI init begin
[blitzBUS] LCD SPI init PASS
[blitzBUS] LCD panel init begin
[blitzBUS] LCD panel init PASS
[blitzBUS] LCD clear begin
[blitzBUS] LCD clear PASS
```

If the run stops at one of these checkpoints, the precise step is known.
The existing runner still builds the full microDOS Pico matrix as part of
`md.bat build pico`. This is not yet optimized to build only blitzBUS.

Firmware compile/flash and physical LCD behavior **not tested by this package**.
