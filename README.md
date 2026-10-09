# blitzBUS v38 — XIP counters for the PSRAM question

On top of v37 (your PIC/PIT/IRQ work, unchanged). Pair with blitz86 (j).

* `bb_xip_misses()` read the RP2350 XIP counters as a free-running difference,
  but `CTR_ACC`/`CTR_HIT` **saturate** at 2^32-1 (~15 s at 300 MHz), so
  `native-misses` turned to garbage. They are now read-and-cleared on every
  call and accumulated in 64 bits.
* The `[bb-jit]` line gains `xip-access=`, `xip-miss=` (both cores, flash +
  PSRAM) and `native-miss=` (misses while blitz86 code was running) per
  interval. Side effect: microDOS's own `[xip]` boot statistics read the
  cleared counters and are no longer meaningful after the live backend starts.
* `tests/bb_3dbench.c`: `FB_DUMP=file` writes the final mode 13h screen and
  palette; `-DB86_COND_HISTO` dumps per-site C-call histograms.

Host check: 3DBENCH runs to its score screen with your v37 IRQ code
(33.3 on qemu, meaningless as a number but proves the timer path).

---

# blitzBUS v0.9 — blitz86 performance pass for 3DBENCH

Requires blitz86 (i) (`b86_jit_set_hot_threshold`, new stats fields).

## What changed

* **Tiering on**: blitz86 interprets an entry point until it has been
  dispatched `BB_HOT_THRESHOLD` (default 128) times in the current code-cache
  generation. 3DBENCH's hot loops stay resident in the 192 KiB SRAM code
  buffer instead of the whole cache being flushed every frame.
  Host measurement (Thumb-2 under qemu, 250M instructions): flushes 959 -> 6,
  translation 17.5 s -> 0.22 s, total 114 s -> 14 s. qemu exaggerates
  translation cost, so expect a smaller (but still large) gain on the Pico.
* **Ctrl+] works during VGA**: once mode 13h starts, `bb_v23_poll_input` is
  the only serial reader; it now prints the stats on 0x1D instead of queueing
  it as a guest keypress.
* **Periodic `[bb-jit]` line** after each `[bb-v25]` (every 8192 slices):
  deltas of native/translate time, flushes, blocks translated, interpreted
  ("cold") instructions, C round trips by kind, joins/in-block branches/splits.
  Healthy 3DBENCH: `flushes=0`, `translate-ms` near 0, `rt-step` small.
* The leftover v13 256-dispatch diagnostic budget after mode 13h is removed.
* PSRAM metadata arena 384 -> 768 KiB (join bitmaps and heat table).
* Host builds pass real time to the VGA status/gameport ports.
* `tests/bb_3dbench.c` + `tests/build_3dbench.sh`: the 3DBENCH host profile.

## Build knobs (environment, read by `install_live.py`)

    BB_HOT_THRESHOLD   0..255, default 128 (0 = translate everything at once)
    BB_CODE_KB         64..288, default 192 (SRAM code buffer)

Same run command as before.

## What to look for

`[bb-jit] ... flushes=0 ...` during the benchmark. If flushes stay above a few
per line, try `BB_HOT_THRESHOLD=200` or a larger `BB_CODE_KB` (the link fails
if SRAM overflows; blitz86 reports `fail=jit-create` if the heap runs out).

---

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
