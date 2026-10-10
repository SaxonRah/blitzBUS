# blitz86 P1 zero-page-delta specialization (experimental)

Full replacement files: `be_t2.c` (based on EA_IMM12 v1), `jit.c`, `b86.h`. No patches. This is **not yet hardware-tested**.

When all 512 page-delta slots are zero, JIT emission skips the 3-instruction page-table translation for DS/ES/CS memory accesses. Once any page is mapped, future blocks use the unchanged full translation, and existing blocks are conservatively flushed **before** map/unmap publishes changes. SMC checks remain in force. This uses `B86_OPT_PAGE_ZERO=1`; default is off. Existing `B86_EA_IMM12_FAST=1` remains supported.

## Installation

```powershell
cd C:\blitzBUS
Expand-Archive "$HOME\Downloads\blitz86_pagezero_v1.zip" C:\blitzBUS -Force
.\blitz86_pagezero_v1\install.ps1 -Mode Install
```

Installer compares SHA256 against the captured source and previous EA v1 `be_t2.c`, and backs up your three source files. If `jit.c` or `b86.h` changed, installer refuses rather than overwriting. There is no automatic CMake edit.

## Enable

Add next to existing `B86_EA_IMM12_FAST=1` target definition **inside the actual live DOS target**, after the target is created:

```cmake
target_compile_definitions(blitzbus_pico_b86_dos PRIVATE B86_OPT_PAGE_ZERO=1)
```

With the optimized `be_t2.c` and `jit.c`, build with the exact known-good `bb_live_run.ps1` invocation at 300 MHz / 75 MHz SPI / LCD lace. Check the generated `build.ninja` for `B86_OPT_PAGE_ZERO=1`.

## Test and interpretation

Run `DOS2TEST`, `MDSTRESS`, `3DBENCH` and note result vs 35.7. The optimization will affect code emitted before any page mapping, and code emitted again after all mapping is removed. After VGA A000 and BBUF maps, the page table is nonzero and JIT emits the original path. Thus **3DBENCH may see little benefit**, which is an expected limitation, not a bug. Instrumentation and separate map-local specialization remain future work. Monitor extra flush counts during mapping transitions.

## Critical caveats

- `map_range`/`unmap_range` must be invoked while native translated code is not executing. This is an existing required contract for modifying shared page tables, but now also essential for cache-generation safety.
- Struct `B86Cpu` gains one `uint32_t` field. All user code must be rebuilt together, not mixed from old object files.
- This is a conservative first phase of pass 1; **not** the full four-optimization rollout. No measured gain is claimed.
- To switch OFF, change compile definition to `B86_OPT_PAGE_ZERO=0` and rebuild. To restore source files: `install.ps1 -Mode Restore` (after removing the P1 macro).
