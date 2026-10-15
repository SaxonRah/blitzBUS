# blitzBUS IRQ0 bridge regression V2

## Purpose

V1 passed 89 checks on the actual microDOS runtime and a synthetic PIC-style frame. This next step also exercises **the current `C:\blitz86_v2\src\interp.c` reference CPU** through the exact register/segment/FLAGS handoff used by `C:\blitzBUS\src\bb_live.c`.

It compares an unclaimed microDOS vector-8 interrupt + microDOS interpreter handler to blitzBUS-style PIC entry + blitz86 interpreter handler (both one continuous slice and handoff after every instruction). It repeats ordinary stack (`0E51:E214`), wrap at SP=0004, and wrap at SP=0000, for models 8086, 286, and 386. A deliberate corrupted-frame control validates only the observed zero-return *symptom*, not its cause.

No 386 protected mode, real DOS 6.22 BIOS handler, or Thumb-2 JIT is executed by this hosted test. Those require additional evidence.

## Run in PowerShell

Extract the ZIP **directly** into `C:\blitzBUS`, preserving the `bb_irq0_bridge_v2` subdirectory. The existing V1 folder is not modified.

```powershell
cd C:\blitzBUS
Expand-Archive "$HOME\Downloads\BLITZBUS_IRQ0_BLITZ86_BRIDGE_V2.zip" C:\blitzBUS -Force
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bb_irq0_bridge_v2\run_host.ps1
```

If you only want to validate source paths and stage an isolated MSVC-compatible copy (no compilation):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bb_irq0_bridge_v2\run_host.ps1 -NoBuildMicroDOS -PrepareOnly
```

The runner:
1. Builds `C:\microDOS\build-host\Release\microdos_runtime.lib` if needed.
2. Reads the actual local blitz86 `src/interp.c` and its five `.inc` files; prints original SHA-256 hashes.
3. Creates temporary copies **only** within `C:\blitzBUS\bb_irq0_bridge_v2\build-host\blitz86`; removes GNU-only attributes in those copies to allow MSVC compilation. Original source files remain untouched.
4. Compiles the host regression with MSVC, links your existing microDOS runtime library, and executes assertions.

The converter removes **compiler hint attributes** such as `cold`, `noinline`, and `section` from the staged copies only. It replaces GCC's `__builtin_expect` hint with `(expr)`; no instruction behavior is intentionally changed.

## What success means

If the output reports `RESULT ... failures 0`, then current microDOS and blitz86 interpreter implementations agree on this simple IRQ handler and stack flow, including per-instruction state transfers. **This does not establish that the Pico Thumb-2 JIT preserves state.** The next milestone is a bounded, nondestructive Pico JIT handoff trace or a native Thumb-2 test on an ARM test runner.

If compilation fails, provide the first actual C compiler errors. MSVC might reject other GNU-specific syntax introduced since the audited repository version. Do not modify your actual `C:\blitz86_v2` checkout to work around it; we can revise the isolated adapter.

## Repository hygiene

Do not `git add -A`. This is an experimental host test in an untracked folder and its `build-host` is transient. Keep earlier `.bb*state` trees and `DOS622_HDD.IMG` untouched. Do **not** re-arm guest IRQ0 Ctrl+U on the Pico yet.
