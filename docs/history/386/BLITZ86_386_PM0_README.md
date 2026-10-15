# blitz86 PM0 — RP2350 386 execution probe + protected-mode descriptor groundwork

**Verified baseline:** RM3 firmware previously ran DOS 2.00 in 80286 real mode at **62.5** (three repeat measurements reported), with `RCXTEST 64/64`, `T2ECPU 8642`, a **232 KiB JIT executable buffer**, and **521,864 / 524,288 B (99.54%) SRAM usage**. The present milestone has **not yet been linked or run on the Pico**; the new build must be checked separately.

This is the first *on-device 386 interpreter-validation* milestone. It does **not** enable protected mode, 386 JIT execution, 32-bit protected linear addressing, paging, or Descent. The protected-mode groundwork is a safe descriptor parser and GDT lookup helper, which future PM1 selector loading and privilege checks can reuse.

## Files — full source, not patches

- `bb_386_pm0_v1.py`: reversible installer (`selftest`, `probe`, `apply`, `verify`, `restore`) with SHA256 original-source backups and explicit anchor checking.
- `b86_pm0.h`: public descriptor representation and checked decoding/GDT query interface.
- `i386_pm0.inc`: flash-placed 386 descriptor decoding, 20-bit limit expansion, 32-bit base assembly, G/B/DB/access/DPL checks, and GDT selector/bounds checks. **No PE transitions or exceptions.**
- `bb_386_pico_probe.inc`: optional boot-time Pico test, run before creating the 286 JIT. Uses a separate B86Cpu allocated in PSRAM, backs up and restores `[0x100000,0x1003ff]` of the guest HMA, and calls actual `b86_step()` under CPU model 386.
- `bb_386_pm0_smoke.c`: 21-assertion host GDT/descriptor suite.
- `bb_archive_62_5.ps1`: archives the previous firmware, full relevant source files, and SHA256 manifest.

The installer modifies **only** `C:\blitz86_v2\src\interp.c` (adds one `#include` for the flash functions) and `C:\blitzBUS\src\bb_live.c` (adds the opt-in probe include and startup call). It creates four additional source/test files in their correct folders. `src/jit.c`, `src/be_t2.c`, `include/b86.h`, existing RM0–RM3 instruction files, executable cache size, and the normal CPU model remain unchanged.

## Install

Extract ZIP files into `C:\blitzBUS`, keeping its directory structure. Preserve the current baseline **before** application:

```powershell
cd C:\blitzBUS
powershell -NoProfile -ExecutionPolicy Bypass -File .\bb_archive_62_5.ps1
python .\bb_386_rm3_v1.py verify
python .\bb_386_pm0_v1.py selftest
python .\bb_386_pm0_v1.py probe
python .\bb_386_pm0_v1.py apply
python .\bb_386_pm0_v1.py verify
```

PM0 includes the Pico smoke test by default; after its compilation it prints one of:

```
[bb-386-pico] PASS 10/10 386 interpreter+GDT, guest HMA restored
[bb-386-pico] FAIL test=N passed=M/10 (286 boot continues)
```

The 10 steps test `66h` EAX immediate/MOV AX upper-register retention/ADD, combined `66+67` SIB indexed load, FS override load, `66h` CALL/RET and 32-bit SS stack handling, 386 descriptor decode and invalid GDT bounds. This is **not** a DOS COM program; it executes before the existing DOS/JIT start, then the test window is restored byte-for-byte and regular DOS execution proceeds in model 286. The native JIT never runs under the 386 model during this test.

The HMA probe needs the boot guest memory to be at least `B86_MEM_BYTES`, as in the current log (1088 KiB). CPU and save buffer are in PSRAM rather than using another 5 KiB of SRAM. The Pico linker must still confirm the executable SRAM budget. If you need to suppress the probe in a custom build, define `BB386_PICO_PROBE=0` as a compiler definition; the descriptor decode API can remain installed.

### Pico build and regression

```powershell
cd C:\blitzBUS
$env:BB_CPU = '286'
$env:BB_CODE_KB = '232'
$env:BB_HOT_THRESHOLD = '32'
$env:BB_EVICT_CHUNK = '4096'
$env:BB_EVICT_ROOM = '2048'
$env:BB_NO_CHAIN = '0'

powershell -NoProfile -ExecutionPolicy Bypass `
    -File .\scripts\bb_live_run.ps1 `
    -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180
```

At boot expect `[bb-386-pico] PASS 10/10 ...` *before* `[bb-v63-cpu] blitz86 CPU model 80286 (real mode)`. Thereafter run `RCXTEST`, `T2ECPU`, `3DBENCH` in `C:\BENCH`; compare to the 62.5 baseline, and confirm SRAM under 524288 B. A changed 3DBench value need not indicate 286 semantic regression: code-layout/XIP cache behavior can move scores. Keep the full benchmark log for comparison.

### Host descriptor test

Run after `apply`, in WSL:

```bash
cd /mnt/c/blitz86_v2
mkdir -p build
gcc -O2 -Wall -Wextra -Iinclude src/interp.c \
    tests/bb_386_pm0_smoke.c -o build/bb_386_pm0_smoke
./build/bb_386_pm0_smoke
```

Expected: `BB386 PM0 PASS: 21 checks, 0 failed`.

**Validation performed for this package:** 21 PM0 descriptor assertions passed with GCC and Clang; 10 386 test steps passed with a synthetic RM0+RM1+RM2+RM3 host interpreter bridge, with guest-HMA restoration validated. GCC AddressSanitizer/UBSan runs passed. Installer passed LF and CRLF byte-exact apply/verify/restore selftests. **Real `src/interp.c` and on-silicon compilation still require your local build**, so this is not a claim that RP2350 has already passed the 386 smoke test.

## Rollback

```
cd C:\blitzBUS
python .\bb_386_pm0_v1.py verify
python .\bb_386_pm0_v1.py restore
python .\bb_386_rm3_v1.py verify
```

Do not attempt to verify/restore RM3 **before PM0** when PM0 has modified `src/interp.c`.

## Next protected-mode milestone (PM1)

Extend descriptor caches for all six segments and implement safely switchable CR0.PE, 32-bit CS:EIP, SS:ESP and access checking, and exceptions (`#GP`, `#SS`, `#NP`, `#UD`) with correct non-destructive fault delivery. Rework linear-to-physical translation for PSRAM-backed extended guest memory before enabling paging or DOS extenders. Continue using 286 native Thumb-2 translation by model while 386 protected mode executes in interpreter first. Do not claim full protected mode until descriptor-loading, gates, interrupts, and tests exist.
