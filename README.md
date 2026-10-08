# blitzBUS v0.8.3 — blitz86 owns DOS execution

v0.8.3: measurement. Requires blitz86 (h).
* XIP/QMI misses attributed to native execution and to translation.
* `[bb-live-delta]` line: per-Ctrl+] deltas (retired, native ms, translate
  ms, blocks, misses, C round trips by kind, BIOS traps).
* `-PhaseProfile`: after the normal PASS flow, runs `MDSTRESS 1`..`9` one at
  a time with counters after each and prints a per-phase table (also in the
  JSON report as `phases`). Use a longer window:

      .\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 400 -AutoTests -PhaseProfile

---

# blitzBUS v0.8.2

v0.8.2: requires blitz86 (g). The previous hardware run spent most native
time in 2.5M interpreter-helper round trips (rotates, PUSHF/POPF, SAHF/LAHF,
MUL flags, DIV); blitz86 (g) runs them natively (50K helpers left). bb_live
now syncs only the ~10 pages that hold translated code (sync was 259 ms).

---

# blitzBUS v0.8.1

v0.8.1 (after the first hardware run: correct, but slower than the
interpreter because of XIP/QMI cache misses):
* microDOS filters its own stores byte-exactly (TRBYTES bitmaps fed by
  blitz86's code hook, 64 pages x 512 B in SRAM): page syncs 6,513 -> 399.
* blitz86 code runs from SRAM (`B86_RAM_FUNCS=1`), not flash XIP.
* Dispatcher re-entries hit the SRAM fast table first.
* New stats line: `[bb-live-time] native= ms (translate= ms) sync= ms
  flushes= dispatches= fast=` — the next hardware run shows where time goes.

---

# blitzBUS v0.8

v0.8 replaces the read-only differential gate with an **owner-mode** live
backend: blitz86 runs the guest natively inside microDOS's DOS system loop
and commits state after every slice.

* microDOS keeps its BIOS segment (driver trampolines), its INT hooks
  (console/disk/clock) and port I/O; blitz86 runs everything else.
* microDOS writes (disk DMA, BIOS code) are detected through its per-page
  write generations and invalidated byte-exactly (shadow copy in PSRAM).
* Retired instructions are counted exactly, so budgets, console polling and
  `[perf]` MIPS remain correct.
* RP2350 layout: 192 KiB code buffer + 32 KiB hot tables in SRAM; blitz86
  metadata (384 KiB arena) and the shadow in PSRAM; 1 ms slice timer.

Requires blitz86 (e) or later (`trap_cs`, `b86_jit_set_count_retired`,
`b86_jit_sync_external`, `B86_CALLOC`).

## Run on hardware (unchanged command)

```powershell
cd C:\blitzBUS
.\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180 -AutoTests
```

Ctrl+] prints, after the usual `[perf]` block:

    [bb-live] backend=blitz86-thumb2 retired=N blocks=N ready=1     (parsed by the script)
    [bb-live-owner] slices= traps= hooks= page-syncs= code-lines-changed= halts= fail=
    [bb-jit] last-rc= chains= smc-inval= helpers=

`fail=` names the reason if the backend refused to start (e.g.
`guest-not-64-aligned`); microDOS then keeps interpreting.

## Host / qemu end-to-end test (no hardware)

Boots the real MS-DOS 2.0 through microDOS's portable DOS loop with this
backend, runs DOS2TEST and MDSTRESS with scripted input:

```sh
tests/build_e2e.sh /path/to/microDOS /path/to/blitz86 build-e2e
qemu-arm     build-e2e/bb_dos_e2e_t2  MSDOS.SYS disk.img --quiet --expect-checksum 0xA298
qemu-aarch64 build-e2e/bb_dos_e2e_a64 MSDOS.SYS disk.img --quiet --expect-checksum 0xA298
```

(`--interp` runs the microDOS interpreter alone for comparison.) The disk
image is microDOS's `mkfat12 --command COMMAND.COM --add DOS2TEST.COM ...
--add MDSTRESS.COM ...`.

Verified (qemu, both ISAs): DOS2TEST 25/25, MDSTRESS 0xA298, blitz86 retired
99.9% of 18.78M instructions. Not yet run on hardware.

## Files

    src/bb_live.c/.h        owner-mode backend
    scripts/install_live.py generator for the opt-in firmware target
    tests/bb_dos_e2e.c      host end-to-end harness
    tests/build_e2e.sh      ARM cross builds of the harness
    tests/gen_system.py     same system-loop patch the installer applies

---

# blitzBUS v0.7.6.2 — JIT counter-gate correction

This overlay replaces only `src/bb_live.c` and `src/bb_live.h`. It retains the v0.7.6.1 installer, LCD, COM console, reference-first execution, and diagnostics.

The previous adapter treated `B86JitStats.guest_insns` incrementing by exactly one as a mandatory condition. The prior hardware log showed `B86_BUDGET` (3), correct next IP, but `delta=0` on the fourth candidate (CLD). `guest_insns` is diagnostic telemetry; it is not a reliable single-dispatch correctness oracle.

v0.7.6.2 requires `B86_BUDGET` and compares the resulting CS, IP, general/segment registers and defined FLAGS against the authoritative interpreter step. If a comparison differs, further JIT validation is disabled. The JIT state is never committed.

Install: extract ZIP into `C:\blitzBUS` (the ZIP contains `src/` at its root), replacing files.

```powershell
cd C:\blitzBUS
.\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180 -AutoTests
```

Do not use `-NoBuild` or `-NoFlash`. Hardware tests are not yet run.
