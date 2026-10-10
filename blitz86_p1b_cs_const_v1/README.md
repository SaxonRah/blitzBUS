# blitz86 P1b: CS absolute-address page specialization (experimental)

This is a **real, narrowly scoped** per-page optimization building on the working Page-Zero v1 sources. It is NOT the general per-block guard for dynamic memory references. The latter requires additional translation metadata and dynamic register/segment guards; do not treat this version as delivering it.

## What it changes

`be_ea()` specializes a memory operand only when all conditions hold:

* Segment override is CS and effective address is absolute 16-bit offset (`b1` and `b2` absent).
* The concrete host-address page is not currently remapped (`cpu->pt[page] == 0`).
* Address is not the final byte of its 4-KiB page, because 16-bit accesses might cross the page boundary.
* Both `B86_OPT_CS_CONST=1` **and** `B86_OPT_PAGE_ZERO=1` are enabled, ensuring P1 map/unmap generation flushes.

For eligible EAs it skips the normal runtime `UBFX / LDR delta / ADD` translation, even when **some other** guest page is remapped. DS/ES indexed accesses, MOVS, STOS, general code, and mapped CS pages still use the original translation. SMC checks remain unchanged. Consequently **3DBENCH may not measurably improve** because its major loop uses dynamic memory and mapped VGA/buffer pages.

## Install

```powershell
cd C:\blitzBUS
Expand-Archive "$HOME\Downloads\blitz86_p1b_cs_const_v1.zip" C:\blitzBUS -Force
.\blitz86_p1b_cs_const_v1\install.ps1 -Mode Install
```

The installer SHA-checks your current `be_t2.c` against **Page-Zero v1** and backs it up before replacing. Does not alter other sources or CMake.

## Enable

Add this **after the live target is created** in `C:\microDOS\pico\CMakeLists.txt` next to the other compiler definitions:

```cmake
target_compile_definitions(blitzbus_pico_b86_dos PRIVATE
    B86_OPT_PAGE_ZERO=1
    B86_OPT_CS_CONST=1
    B86_EA_IMM12_FAST=1)
```

Run the normal `bb_live_run.ps1` at 300MHz, 75MHz SPI, lace 1. Confirm `B86_OPT_CS_CONST=1` and `B86_OPT_PAGE_ZERO=1` in `build.ninja`. Run DOS2TEST, MDSTRESS and 3DBENCH; compare multi-run score distributions, not a single best score.

Disable P1b only by setting `B86_OPT_CS_CONST=0` (keep P1 enabled). To restore the exact previous `be_t2.c`, use `install.ps1 -Mode Restore`.

## Validity limits

* Only JIT compilation on the current CS:IP path and existing far-control-transfer block boundaries make the CS base stable.
* Map/unmap must happen outside native execution, with the P1 cache flush **before** mapping publishes new deltas.
* Mapping and memory cross-page correctness are preserved as in existing P1; no new handling for a word crossing remapped pages is added.
* No Pico run or 3DBENCH measurement has been performed on this revision.

Next, for meaningful per-block dynamic operand specialization, instrument page-delta lookup frequency and identify hot dynamic operand sites before adding potentially more expensive runtime guards.
