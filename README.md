# blitzBUS VGA mode 13h bring-up v1

Targets DOS `3DBENCH`, without touching `C:\blitz86_v2`. Includes 6 requested capabilities:
INT 10h mode 03/13 and get-mode, mapped guest RAM A000:0000, DAC indexed writes/reads,
time-varying VGA 3DA, LCD RGB565 480x300 presentation, and absent-gameport readback.

**Not yet full VGA**: no planar graphics, no VESA, no BIOS character graphics services,
no proper timer/PIT or Sound Blaster, and no Descent protected mode. Initial 3DBENCH
might still freeze on another unimplemented BIOS service. Unhandled INT 10h functions
fall through to existing handling, and are not treated as success.

## Install

1. Extract into `C:\Users\Jupiter\Downloads\blitzbus_vga_v1`.
2. Because the diagnostic source has been modified repeatedly, restore a good local
   `bb_live.c` from the pre-diagnostic backup first, preserving your current blitz86:

```powershell
cd C:\blitzBUS
Copy-Item .\src\bb_live.c .\src\bb_live.c.before_vga -Force
Copy-Item .\src\bb_live.c.before_3dbench_diag .\src\bb_live.c -Force
py "$HOME\Downloads\blitzbus_vga_v1\scripts\INSTALL.py" --repo C:\blitzBUS
if ($LASTEXITCODE -ne 0) { throw 'Generator failed; stop' }
Copy-Item .\src\bb_lcd_console.c .\src\bb_lcd_console.c.before_vga -Force
Copy-Item .\src\bb_lcd_console.h .\src\bb_lcd_console.h.before_vga -Force
Copy-Item "$HOME\Downloads\blitzbus_vga_v1\OUTPUT\src\*" .\src\ -Force
cmake --build C:\microDOS\build-pico\out --target blitzbus_pico_b86_dos
if ($LASTEXITCODE -ne 0) { throw 'Build failed; do not flash' }
```

3. Re-run `bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180`.
   **Do not pass -AutoTests**, the 3DBENCH disk does not contain DOS2TEST.
4. At `A>` type `3DBENCH`. On return to DOS, text display is restored.

## Implementation notes
- `bb_vga.c` is included as a translation unit from `bb_live.c` to avoid changing CMake files.
- Guest writes go to already-mapped guest RAM and the LCD reads it in strips.
- LCD uses one 480x3 stripe per tick, bounding the time spent in each loop.
- No claims of hardware validation; user must compile/run on actual board.
- The historical `bb_live.c.before_3dbench_diag` was created during earlier test steps.
