# WINFIX2 — Ninja manifest regeneration loop

The build output reached `[0/100] Re-running CMake` and then
`ninja: error: manifest 'build.ninja' still dirty after 100 tries`.

WINFIX2 retains WINFIX1's validated ARM GCC/Ninja/SDK discovery, and
adds `CMAKE_SUPPRESS_REGENERATION=ON` to the **isolated** V3 target.
The PowerShell build launcher runs CMake's configure step explicitly
each time, so suppressing Ninja's automatic configure retries is safe.
This does not modify C:\microDOS, C:\blitz86_v2, or the Pico flash.
It reuses `build-pico-ninja` without deleting any previously generated files.

Run:

```powershell
cd C:\blitzBUS
Expand-Archive `
  "$HOME\Downloads\BLITZBUS_IRQ0_PICO_THUMB2_V3_WINFIX2.zip" `
  C:\blitzBUS -Force
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\bb_irq0_pico_v3\build.ps1
```

Stop after the build, even if it creates a UF2. Do NOT flash yet.
If compilation fails, send the first compiler/linker error and the
final output.

This bypasses the Ninja **regeneration loop**, not actual compiler errors.
When CMake source/flags change, rerun `build.ps1` so CMake regenerates
the build files explicitly.

---

# blitzBUS IRQ0 V3 — Windows Pico SDK build fix 1

**What failed:** The original V3 CMake project included `.pico-sdk/cmake/pico-vscode.cmake`
from an ordinary Windows PowerShell shell. That helper requires VS Code-specific
variables; CMake looked in `/.pico-sdk/sdk` and fell back to the host Visual Studio
generator. No V3 source was compiled, and no firmware was changed.

**What changes:** The full `CMakeLists.txt` and `build.ps1` are replaced with
versions that obtain the existing SDK, ARM compiler and Ninja from
`C:\microDOS\build-pico\out\CMakeCache.txt` first. Fallbacks use your
`$HOME\.pico-sdk` installation. They pass an explicit SDK/toolchain and select
`-G Ninja` using a fresh `build-pico-ninja` directory. No cleanup or overwrite of
the old `build-pico` folder occurs.

## Build ONLY

Extract the ZIP into `C:\blitzBUS` with `Expand-Archive ... -Force`, then:

```powershell
cd C:\blitzBUS
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\bb_irq0_pico_v3\build.ps1
```

If the toolchain layout is unusual, `build.ps1` accepts explicit `-SdkPath`,
`-ToolchainPath`, and `-NinjaPath` overrides. The SDK folder must contain
`pico_sdk_init.cmake`, the toolchain folder `bin\arm-none-eabi-gcc.exe`.

**Stop after build** and send the console output. The V3 firmware has not been
tested against your local Pico SDK or on the hardware, and it would be
premature to flash it. All build outputs stay under
`bb_irq0_pico_v3\build-pico-ninja`. `run_device.ps1` is updated to reference
that new path, but it still requires explicit `-Flash`.

---

# blitzBUS IRQ0 native Thumb-2 V3 — WINFIX3

## WINFIX3 hot-table fix

The paged Thumb-2 backend with `B86_FAST_BITS=10` needs **40 KiB** of
JIT hot-table SRAM (32 KiB code-line map plus 8 KiB fast table). WINFIX2
allocated only 32 KiB. That older firmware builds but its runtime test
would refuse to create the JIT and cannot count as a native regression.
WINFIX3 increases the dedicated hot buffer to 40 KiB and prints the
required/available byte counts. The WINFIX2 Ninja-generator workaround
and `build-pico-ninja` runner path remain intact.

## Purpose

V1 passed 89/89 hosted microDOS IRQ frame/IRET checks. V2 passed
1,002/1,002 real microDOS/blitz86 **interpreter** checks.

V3 moves the next question to **real RP2350 Thumb-2 native execution**.

- Runs a standalone synthetic interrupt handler (PUSH AX, OUT 20h EOI,
  POP AX, IRET) and a loop at the historical return address 0FF2:87A2.
- Compare complete architectural register state, flags, guest-memory FNV
  hash and EOI count against the blitz86 interpreter reference.
- Test model **286**, `B86_PAGED=1`, `B86_MAXB=2048`,
  `B86_MAP_BITS=12`, `B86_FAST_BITS=10`, single-hit and 64-hit JIT
  promotion, initial SP E214/0004/0000.
- Require nonzero JIT block and native-instruction counts to avoid
  reporting a pure interpreter run as a JIT pass.
- Uses the local `C:\blitz86_v2` source files and microDOS Pico PSRAM
  allocation helper, without editing either source repository.
- Deliberately **does not** boot DOS, access SD/FAT, mount images,
  arm host IRQ0, or run Descent.

These are tests of a *synthetic handler*. A PASS is **not** proof that
the real MS-DOS 6.22 IRQ0 handler, PIT/PIC timing, disk I/O or the
entire DOS execution path is correct.

## First: Build, without touching the Pico

Extract all files in this ZIP at `C:\blitzBUS` so the root contains
`bb_irq0_pico_v3\CMakeLists.txt`.

```powershell
cd C:\blitzBUS
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\bb_irq0_pico_v3\build.ps1
```

Expected UF2 after a successful build:

`C:\blitzBUS\bb_irq0_pico_v3\build-pico-ninja\bb_irq0_pico_v3.uf2`

**Stop after build and send the output first.** Build may uncover SDK,
linker or PSRAM-memory-layout issues, and there is no reason to overwrite
working firmware until the isolated target compiles.

## Then: Explicitly flash and capture (only after successful build)

Stop any other COM5 reader. Running the next command **replaces the
current Pico flash program** with the standalone synthetic test. It is
not a non-invasive inspection of the live DOS firmware.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\bb_irq0_pico_v3\run_device.ps1 -Flash -Port COM5 -Seconds 90
```

The script records a raw capture in `bb_irq0_pico_v3\logs\`.
After testing, reflash your previously working
`C:\microDOS\build-pico\out\blitzbus_pico_b86_dos.uf2` to restore DOS.
The existing UF2 file is **not** a byte-for-byte backup of the current
device flash; preserve your actual known-good UF2 if those differ.

## Source files used

The V3 build reads but does not modify:

- `C:\blitz86_v2\include\b86.h`
- `C:\blitz86_v2\src\interp.c`, `jit.c`, `be_t2.c` and included `.inc` files
- `C:\microDOS\pico\b86_hw_alloc.[ch]`
- Pico SDK configuration and runtime

All generated objects and firmware go under `bb_irq0_pico_v3\build-pico`.
`build.ps1` verifies the primary local source hashes after the build.

## Interpretation

- JIT mismatches, failure, hardfault: need diagnostics of Thumb-2 code,
  fallback instruction state, page mapping and register synchronization.
- All tests pass: synthetic native IRET and interrupt return look correct;
  next instrument real DOS IRQ0 handler and the first native slice, with
  one-shot still **OFF** by default.
- JIT native counters zero: not considered a pass, even if CPU registers
  happen to match.
