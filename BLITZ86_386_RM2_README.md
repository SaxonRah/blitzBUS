# blitz86 / blitzBUS — 80386 Milestone RM2: extended `0F` map

**Scope:** Real-mode 386 **interpreter** only. This is the layer after RM0 (`66h`, DWORD data) and RM1 (`67h`, SIB, combined 66+67). The 8086/186/286 source paths, optimized Thumb-2 backend, eager dead-stub unchaining, native memory RCL/RCR, and **232 KiB code cache** are untouched.

**Files delivered:** `bb_386_rm2_v1.py` (full reversible installer), `i386_rm2.inc` (complete new 386 C implementation), and `bb_386_rm2_smoke.c` (self-contained test program, link with the blitz86 reference interpreter). No Git patches.

## Implemented

| Encoding | New behavior | Operand-size modes |
|---|---|---|
| `0F 80`–`0F 8F` | Near Jcc with signed rel16/rel32 | 16/32 |
| `0F 90`–`0F 9F` | SETcc byte register or memory | 8-bit destination, `66h` ignored |
| `0F B6/B7` | MOVZX, byte/word source | 16/32 destination where widening is legal |
| `0F BE/BF` | MOVSX, byte/word source | 16/32 destination where widening is legal |
| `0F AF` | Signed two-operand IMUL, CF/OF | 16/32 |
| `0F BC/BD` | BSF/BSR; zero source preserves destination and sets ZF | 16/32 |
| `0F A3/AB/B3/BB` | BT/BTS/BTR/BTC with register index, including negative memory indexes | 16/32 |
| `0F BA /4..7` | BT/BTS/BTR/BTC with imm8 index | 16/32 |
| `0F A4/A5/AC/AD` | SHLD/SHRD with imm8 or CL count | 16/32 |

These also work with the RM1 `67h` 32-bit ModR/M/SIB effective-address decoder and combined `66h+67h` prefixes. CPU model `B86_CPU_386` selects the new implementation. The existing `0F 01` (286 system instruction group) and `0F 06` (CLTS) keep their preexisting handler.

**Correctness safeguards:** bytes/words written to x86 GPRs preserve higher EAX–EDI halves in 386 mode; all memory operand widths are checked against the current 64 KiB real-mode segment limit; modifying code continues through the RM1 SMC write hooks. The implementation updates flags before an SMC-checked memory store. SHLD/SHRD count zero does not modify destination/flags; count above 16 on 16-bit operands returns `B86_UNSUPPORTED` because the result is architecturally undefined. Other undefined flag bits are left unchanged.

## Install on your current local source

**Do not restore RM1 or RM0 first**—RM2 is installed as a layer on top of RM1. Extract the ZIP directly into `C:\blitzBUS`.

```powershell
cd C:\blitzBUS
python .\bb_386_rm2_v1.py selftest
python .\bb_386_rm2_v1.py probe
python .\bb_386_rm2_v1.py apply
python .\bb_386_rm2_v1.py verify
```

Only `C:\blitz86_v2\src\interp.c` is edited, adding an include and a 386-only `0F` dispatch. The two new source files are `C:\blitz86_v2\src\i386_rm2.inc` and `C:\blitz86_v2\tests\bb_386_rm2_smoke.c`. Original `interp.c` is saved byte-for-byte and hash-verified in `C:\blitzBUS\.bb_386_rm2_v1_backup`. If upstream changes have altered an expected anchor, `probe` or `apply` refuses to modify it.

## Run actual source-compiled CPU tests

With GCC installed in WSL (or use an equivalent Windows GCC/Clang):

```bash
cd /mnt/c/blitz86_v2
mkdir -p build
gcc -O2 -std=c11 -Wall -Wextra -Iinclude \
    src/interp.c tests/bb_386_rm2_smoke.c -o build/bb_386_rm2_smoke
./build/bb_386_rm2_smoke

# Preserve prior milestone coverage
gcc -O2 -std=c11 -Wall -Wextra -Iinclude \
    src/interp.c tests/bb_386_rm0_smoke.c -o build/bb_386_rm0_smoke
./build/bb_386_rm0_smoke
gcc -O2 -std=c11 -Wall -Wextra -Iinclude \
    src/interp.c tests/bb_386_rm1_smoke.c -o build/bb_386_rm1_smoke
./build/bb_386_rm1_smoke
```

RM2 expected:

```
BB386 RM2 PASS: 56 assertions, 0 failed
```

The assertions exercise register-high preservation, signed/unsigned extension, `66h+67h` memory forms, FS-free DS/SS defaults, 32-bit and 16-bit double shifts, signed negative bit indexes into memory, ZF/CF/OF, immediate bit indexes crossing DWORD boundaries, Jcc rel16/32, invalid 0F opcode behavior, 64 KiB real-mode bounds, and 286 isolation.

**Validation completed for this bundle:** an independently compiled C test harness comprising RM0/RM1/RM2 implementation files returned all 56 assertions passing with GCC/Clang and sanitizers; installer passed LF/CRLF, exact-anchor, SHA-backed install/verify/rollback tests. Full upstream `src/interp.c` compilation and Pico firmware build **must be performed in your local checkout**; this bundle does not claim those have already passed.

## Preserve the Pico 286 performance baseline

**Keep the active emulator model 286 for now.** The 386 interpreter is intentionally not performance-ready and should not be used to benchmark JIT speed.

```powershell
cd C:\blitzBUS
$env:BB_CPU = '286'
$env:BB_CODE_KB = '232'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bb_live_run.ps1 `
    -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180
```

From `C:\BENCH`, rerun `RCXTEST` (64/64), `T2ECPU` (checksum 8642), and `3DBENCH` (58.8 target). Check the **actual** SRAM linker report rather than assuming the flash-only handlers cannot change linker alignment or veneers. The 232 KiB code cache must remain intact.

## Restore safely

RM2 is the newest source layer. Restore in **reverse order** only when needed:

```powershell
cd C:\blitzBUS
python .\bb_386_rm2_v1.py verify
python .\bb_386_rm2_v1.py restore
python .\bb_386_rm1_v1.py verify
```

While RM2 is installed, the RM1 installer may report an expected `interp.c` SHA mismatch because RM2 intentionally extended it. Do not run an older restore out of order.

## What remains before Descent

This **does not** yet implement a complete 386 CPU. Missing: FS/GS segmentation and instructions, 386 32-bit protected mode, IDT/GDT descriptors, correct exceptions (#UD/#GP/#SS), 32-bit EIP/interrupt and call gates, paging and TLB, all 386 opcode families, 32-bit string/stack/shift/control-flow variants, DOS extender/DPMI and the required multi-megabyte guest memory. The next architectural milestone should complete missing real-mode cases and FS/GS state, then protected-mode descriptor/exception support and a bigger PSRAM-backed guest-memory window. Only later should we re-enable selected optimized 16-bit Thumb-2 lowerings for model 386 after demonstrating upper-half preservation.
