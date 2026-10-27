# blitz86 / blitzBUS — PM0 Pico include-order fix 1

## Failure

The PM0 boot probe was included immediately after `#include "b86.h"` in `src/bb_live.c`, ahead of the Pico SDK headers. Its two PSRAM allocations therefore attempted to use `__uninitialized_psram(...)` before that SDK macro was available:

```c
static B86Cpu __uninitialized_psram("bb386_probe_cpu") bb386_test_cpu;
static uint8_t __uninitialized_psram("bb386_probe_save") bb386_test_save[1024];
```

The compiler's later `bb386_test_cpu undeclared` messages were cascading errors, not separate failures.

## Change

The standalone Python script moves the **existing** PM0 include block to just before `#ifndef BB_TR_PAGES`, after `<string.h>`, `<stdio.h>`, and the Pico-specific includes. It does not edit the PM0 probe, RM0–RM3, JIT, CPU models, or code-cache configuration. It updates the *installed PM0 SHA manifest* so the original `bb_386_pm0_v1.py verify` and `restore` operations remain valid.

The fixer saves its own exact-byte original source and PM0 manifest in:

`C:\blitzBUS\.bb_386_pm0_include_fix1_backup`

## Install on Windows

Extract `bb_386_pm0_include_fix1.py` into `C:\blitzBUS`.

```powershell
cd C:\blitzBUS
python .\bb_386_pm0_v1.py verify
python .\bb_386_pm0_include_fix1.py selftest
python .\bb_386_pm0_include_fix1.py probe
python .\bb_386_pm0_include_fix1.py apply
python .\bb_386_pm0_include_fix1.py verify
python .\bb_386_pm0_v1.py verify
```

No PM0 reinstall is required. Leave RM3 installed. Do not run PM0 `restore` or `apply` again.

## Rebuild

Use the same known-good configuration:

```powershell
$env:BB_CPU = "286"
$env:BB_CODE_KB = "232"
$env:BB_HOT_THRESHOLD = "32"
$env:BB_EVICT_CHUNK = "4096"
$env:BB_EVICT_ROOM = "2048"
$env:BB_NO_CHAIN = "0"

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\bb_live_run.ps1 `
  -MicroDOS C:\microDOS `
  -Blitz86 C:\blitz86_v2 `
  -Port COM5 `
  -Seconds 180
```

The expected PM0 marker is:

`[bb-386-pico] PASS 10/10 386 interpreter+GDT, guest HMA restored`

The DOS CPU should still report `80286 (real mode)`. Then check RCXTEST 64/64, T2ECPU checksum 8642, and 3DBench against the 62.5 observed baseline.

**The above Pico results are targets, not yet validated for this fix.** Local Python self-tests passed for both LF and CRLF, including exact restoration of the source and PM0 manifest. This fix addresses the presented compile error; any subsequent link or runtime error must be diagnosed separately.

## Undo just this fix

```powershell
python .\bb_386_pm0_include_fix1.py restore
python .\bb_386_pm0_v1.py verify
```

This restores the **prior PM0-installed source**, with the problematic early include, and its prior manifest. To remove PM0 entirely after that, use the original PM0 installer `restore` operation.

## Separate RM3 manifest warning

The log showed `ERROR: RM3 install manifest not found` before PM0 installation. That is unrelated to this compile error. PM0 successfully located RM3 source anchors, but RM3's own backup/manifest should be recovered separately before attempting an RM3 rollback. Do not synthesize or overwrite RM3's missing original-source manifest.
