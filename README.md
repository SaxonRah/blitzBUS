# blitzBUS v51 — HardFault investigation: trustworthy records, quiesced reflash

Pair with blitz86 r51 (the user's current tree + no flush on unmap).

Finding: the v42-v50 "PREVIOUS RUN HARDFAULT" records are not real exception
frames. All six saved PCs are 8-byte aligned (chance ~1/4000 for real Thumb
PCs) and all carry LR=0x10000000 and CFSR=0. The first one followed a run that
finished normally (18.8 fps) and was then reflashed with `picotool reboot -f
-u`, which forces BOOTSEL through the USB reset interface while 3DBENCH is
still running on both cores. The v50 RAM record never survived because the
BOOTSEL bootrom reuses SRAM; the watchdog scratch words did.

* Fault record now lives only in WATCHDOG SCRATCH0-3: core, phase (boot / dos /
  vga / reboot-request), HFSR DEBUGEVT/FORCED/VECTTBL, EXC_RETURN, frame
  address, whether the frame lies inside that core's stack, stacked PC (only
  read when the frame is valid), CFSR. Printed as `[bb-v51-fault]`.
* `reset_usb_boot` is wrapped (-Wl,--wrap): picotool's forced BOOTSEL now
  marks the phase, disables the hang watchdog and stops core 1 before the
  bootrom reboot. A fault in that window no longer overwrites the BOOTSEL
  reboot with its own watchdog reboot.
* Stacks: PICO_STACK_SIZE and PICO_CORE1_STACK_SIZE 0x800 -> 0x1000 (the
  whole SCRATCH_Y / SCRATCH_X banks). `[bb-v51-stack] core0 peak=` in every
  profile report gives the measured high-water mark.
* A000 map/unmap requested by INT 10h is applied between slices, not inside
  the hook (with B86_OPT_PAGE_ZERO a map flushes the code cache, which must
  not happen under the block that called the hook).
* `blitz_swd_faultcatch/`: OpenOCD HardFault vector catch for a live capture.
* Host builds: the v49 sampler init is guarded for non-Pico builds.
* v51b: Ctrl+] reports pause the 3 s hang watchdog while printing (a report
  is ~60 lines and USB CDC printf can block) and presses closer than 1 s
  apart are ignored. Measured core-0 stack peak during reports: 2440 bytes,
  i.e. past the old 2048-byte stack.
* v51c: the time a Ctrl+] report takes is removed from every guest clock
  (BIOS tick base, PIT channel epochs, IRQ0 anchor). The guest is frozen
  while the report prints; before, the BIOS tick jumped and PIT interrupts
  were coalesced, so spamming Ctrl+] broke 3DBENCH's timing.

---

# blitzBUS v47 — window chooser on a wall clock (pair with blitz86 (p))

* The back-buffer window is evaluated every 250 ms of wall time instead of
  every 1024 native slices (with blitz86 (p) slices got longer and the old
  clock could miss the benchmark entirely). Threshold: 128 KiB of REP stores
  per 250 ms.

---

# blitzBUS v46 — back buffer in SRAM too (pair with blitz86 (n))

v45 (A000 in SRAM, 240 KiB code): 22.7. A cache model of 3DBENCH with A000
in SRAM puts 86% of the remaining guest-data misses in the back buffer.

* blitz86 (n) moved the translator to flash (~56 KiB SRAM freed); the
  blitzBUS debug rings bb_v7_ring / bb_v21_steps moved to PSRAM (12 KiB).
* Back-buffer window on again (`BB_BBUF=1` default) with a 232 KiB code
  buffer. `BB_BBUF=0` gives v45's layout (240 KiB, no window).
* The window is now released only for the DOS 2 device-driver vector (0xF1),
  the one microDOS call that touches guest memory. Before, every interrupt
  that reached microDOS released it, including 3DBENCH's own INT 00
  (divide error, which it raises routinely; logged as `[bb-v46] INT 00`).
* If a candidate window is refused, the next best is tried (up to 8); refusals
  print the reason (`rc=-3` translated code in window, `-2` frame placement).
* Host harness: SRAM frames are placed like the Pico's so both windows map.

---

# blitzBUS v45 — A000 window fixed for v44's layout; fuller fault record

Pair with blitz86 (m1).

* v44's 18.8 ran with NO SRAM window: removing the back-buffer frame moved
  the A000 frame to an address blitz86 refused ("A000 window NOT mapped").
  blitz86 (m1) accepts it, so v45 = A000 in SRAM + 240 KiB code buffer.
* The previous run's log showed a HardFault inside generated code
  (pc 0x20034DD0, CFSR 0). A fault now also prints
  `[bb-v45-diag] r0..r3 r12 xpsr hfsr bfar mmfar sfsr sfar exc_lr guest=CS:IP`
  plus the code-buffer range, kept in RAM that survives the reboot.

---

# blitzBUS v44 — SRAM for code instead of the back-buffer window

v43 scored 17.5 with only the A000 window mapped (no `bbuf` line in the log:
the back-buffer window was never mapped). XIP misses were already low
(~1-1.6M per 8 s vs ~9M before v40), but slow phases still interpreted 5-12%
of instructions because warm code did not fit the code buffer.

* `BB_BBUF=0` (default): no 64 KiB back-buffer frame; the code buffer grows
  to 240 KiB (`BB_CODE_KB`). `BB_BBUF=1` restores v43 (176 KiB + frame) and
  now logs `[bb-v44-paged] bbuf ... map refused` if mapping fails.

---

# blitzBUS v43 — cheaper paged accesses (pair with blitz86 (m))

* blitz86 (m): stack (SS) accesses are no longer page-translated and SS is
  cached in r11 again; the page table moved into the SMC line table (r9);
  the add is 16-bit. Smaller paged code -> more fits in the code buffer.
* The back-buffer window is never chosen over the current stack segment,
  and is released if the stack moves into it (required by blitz86 (m)).

---

# blitzBUS v42 — hang / fault diagnostics

v41 froze mid-benchmark on the Pico: the console stopped answering, so core 0
was stuck. v42 records why:

* While mode 13h is active a 3 s hardware watchdog runs, fed every native
  slice, and each slice stores the guest CS:IP in watchdog scratch. A hang
  reboots the board; the next boot prints
  `[bb-v42-diag] PREVIOUS RUN HUNG ... last native slice at guest XXXX:XXXX`.
* A HardFault records PC, LR and CFSR and reboots; next boot prints
  `[bb-v42-diag] PREVIOUS RUN HARDFAULT pc=... lr=... cfsr=...`.
* The watchdog is off at the DOS prompt (text mode), so waiting for input
  never trips it.

To check whether paging is involved, build once with `$env:BB_PAGED = "0"`.

---

# blitzBUS v41 — v40 without the tiering/flush penalty

Pair with blitz86 (l1).

v40 on the Pico cut core 0's XIP misses ~8x (9.4M -> 1.1M per 8 s) but the
score dropped (18.8 -> 12.8): the paged code is bigger and the code buffer
was smaller, flushes rose to ~4 per interval, and each flush reset tiering
heat so ~2.6M instructions per interval ran interpreted (cold-insns).

* blitz86 (l1): flushes keep hot entries hot.
* Code buffer back up to 176 KiB (`BB_CODE_KB`), paid for by the byte-exact
  tracked-page pool: `BB_TR_PAGES` 64 -> 24 (DOS runs used 15; when full it
  falls back to page-level tracking).
* Healthy run: `flushes` 0-1 and `cold-insns` well under 1M per `[bb-jit]` line.

---

# blitzBUS v40 — SRAM-backed frame buffers (blitz86 paged memory)

Pair with blitz86 (l). Default on (`BB_PAGED=1`); `BB_PAGED=0` builds v39a.

* blitz86 is built with `B86_PAGED`: guest pages can live in SRAM.
* **A000 window** (64 KiB) moves to SRAM while mode 13h is active; bb_vga
  and the LCD presenter read the SRAM copy (core 1 no longer reads PSRAM).
* **Back buffer**: about once a second the 16 consecutive conventional-memory
  pages with the most REP STOS/MOVS traffic move to SRAM (3DBENCH: its back
  buffer). Copied back to PSRAM before any call into microDOS (HLE
  interrupts, BIOS-segment slices) and re-chosen later.
* Memory: code buffer default 160 KiB (`BB_CODE_KB`), `bb_hot` 40 KiB (32 Ki
  SMC line map), two 64 KiB SRAM frames. The guest buffer is placed at
  2 MiB-aligned + 640 KiB in PSRAM (up to ~2.6 MiB extra PSRAM).
  If the link overflows RAM or the heap runs out (`fail=jit-create`), try
  `BB_CODE_KB=144`.
* Log lines: `[bb-v40-paged] A000 window -> SRAM`, `bbuf XXXXX-XXXXX -> SRAM`,
  `bbuf ... back to PSRAM (reason)`.
* Known limits: a 16-bit access straddling a window's first/last byte is not
  exact; DOS file I/O straight into A000 while mode 13h is active is not
  seen by the screen.

---

# blitzBUS v39a — PSRAM measurements (calibration moved to Ctrl+T)

On top of v38. Pair with blitz86 (k).

* **Ctrl+P** toggles the LCD presenter (core 1 parks and stops reading
  PSRAM). Each toggle prints a `[bb-jit]` interval line first, so press
  Ctrl+P, wait ~10 s, press Ctrl+] for the paused interval, press Ctrl+P
  again: the `xip-miss` and MIPS of the two intervals give core 1's share.
* **Ctrl+T** prints **`[bb-v38-psram]`** (v39a: on demand, no longer at
  boot): measured cost of an XIP cache miss on
  guest PSRAM for a read and for a read-modify-write (8-byte lines, 32768
  lines each, using the 64 KiB above 1 MiB that DOS 2.0 never touches).
  This turns `xip-miss` counts into time.
* `tests/bb_3dbench.c` prints REP traffic by segment under
  `-DB86_COND_HISTO`.

---

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
