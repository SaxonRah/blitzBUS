# blitzBUS — DOS 6.22 Startup Heap Rescue v1

**Based on the user's updated source in `SaxonRah/blitzBUS`, October 13, 2026.**

## What the latest hardware run actually says

Successful:

- `bb_386_pico`: `PASS 10/10`
- `b86_init()` and CPU model selection
- Build/link/flash; 232 KiB code cache configured

Failing at:

```
[bb622-diag] 07 before.jit_create
*** PANIC ***
Out of...
```

The DOS6 boot-sector read has *not* been attempted on that run. The earlier `[bb-v51-fault] PREVIOUS RUN HARDFAULT` line records a **previous** run, not proof that this run hard-faulted. The panic's truncated text is strongly consistent with the Pico SDK `malloc` wrapper's `Out of memory` panic. The linker reports **522,492 / 524,288 B SRAM, only 1,796 B nominally unallocated** before runtime heap use. The JIT allocates its hot `J` struct and a 2,048-byte dead-block table via ordinary `calloc()` (SRAM), while most other JIT metadata uses the preallocated PSRAM arena.

## Fix

Keep 16 translated-byte write-tracking bitmaps in SRAM and place the remaining 8 (4096 bytes) in external PSRAM:

- Original: 24 × 512 B = **12,288 B** SRAM.
- New: 16 × 512 B = **8,192 B** SRAM, 8 × 512 B = **4,096 B** PSRAM.
- Recover approximately **4,096 B SRAM**.
- The first 16, which covered the existing DOS2/3DBench peak of 15 tracked pages in prior logs, remain hot.
- Each bitmap is zeroed when allocated, so `__uninitialized_psram` is safe for this pool.
- **No change to `BB_CODE_BYTES`, `bb_hot`, 286 JIT implementation, interpreter, BIOS or SD driver.**
- For host builds (`PICO_ON_DEVICE=0`), original contiguous pool is retained.

Important: this is a **targeted memory-capacity fix**, not proof that the DOS6 bootloader is otherwise functional. Once JIT allocation succeeds, we can inspect the retimed SD read and BIOS boot path.

## Installation

Extract this bundle to `C:\blitzBUS`. It contains a complete `bb_dos622_heap_rescue_v1.py` installer (not a Git patch). It edits only the two known source statements in `src/bb_live.c`; it refuses to touch source whose hashes do not match the existing IPL/diagnostic manifests. It updates *both* existing SHA manifests and keeps byte-exact copies of their originals.

```powershell
cd C:\blitzBUS
python -m py_compile .\bb_dos622_heap_rescue_v1.py
python .\bb_dos622_heap_rescue_v1.py selftest
python .\bb_dos622_heap_rescue_v1.py probe
python .\bb_dos622_heap_rescue_v1.py apply
python .\bb_dos622_heap_rescue_v1.py verify
python .\bb_dos622_boot_diag_v1.py verify
python .\bb_dos622_ipl_v1.py verify
```

The old boot diagnostic must be installed (as in your last log) and the IPL manifest must be present. If an integrity check fails, the script stops without editing files.

Rebuild/flash using the **same settings**:

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
  -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 `
  -Port COM5 -Seconds 180
```

## Look for

First, linker RAM usage should drop by roughly 4096 bytes (assuming unchanged build settings). Then:

```
[bb622-diag] 07 before.jit_create
[bb622-diag] 08 after.jit_create
[bb-r52] code-cache 232 KiB, ...
[bb622-diag] 09 before.bios_hook
[bb622-diag] 10 before.dos622_boot
[bb622-diag] 11 enter.boot_floppy
[bb622-diag] 12 before.sector0
[bb-dos622-clockfix] spi1 old=... new=12500000 ...
[bb-dos622] read lba=0 OK
[bb622-diag] 14 sector0.OK
[bb622-diag] 16 after.copy_boot_sector
[bb-dos622] ENTER real boot sector 0000:7C00 ...
```

These are **expected diagnostics**, not verified RP2350 results. If `08` appears but 6.22 doesn't boot, next investigate BIOS INT13 and DOS6 bootstrap instruction flow.

## Restore

Reverses only this fix. The earlier boot-diagnostic and DOS622 IPL installers remain present:

```powershell
cd C:\blitzBUS
python .\bb_dos622_heap_rescue_v1.py verify
python .\bb_dos622_heap_rescue_v1.py restore
python .\bb_dos622_boot_diag_v1.py verify
python .\bb_dos622_ipl_v1.py verify
```

Do **not** restore the earlier diagnostic while the heap rescue is installed; restore the heap rescue first because of parent SHA dependencies.

## Tests run locally before packaging

- Python 3 syntax compilation and LF/CRLF/mixed source + manifest rollback self-tests.
- GCC and Clang with `-std=gnu11 -O2 -Wall -Wextra -Werror` for `PICO_ON_DEVICE=0` and `1` with 16, 24 and 32 tracking pages.
- These were **synthetic C compile tests**, not a complete Pico SDK link or a physical-board run.
