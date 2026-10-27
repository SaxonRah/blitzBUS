# blitz86 — 80386 real-mode milestone 1: 67h/SIB addressing

This release implements **real 80386 address-size override instructions** in the reference interpreter while retaining the validated **8086/186/286 native Thumb-2 JIT** *unchanged*. It is a layered, reversible source-file modification, not a Git patch.

## CPU-model separation

| CPU model | Instruction path | Behavior |
|---|---|---|
| `B86_CPU_8086` | Existing Thumb-2/A64 JIT | Unchanged; 66h/67h retain old model semantics |
| `B86_CPU_186` | Existing JIT + helper | Unchanged; native 186 additions retained |
| `B86_CPU_286` | Existing optimized Thumb-2 JIT | **Unchanged**, current blitzBUS production default |
| `B86_CPU_386` | Reference interpreter | Adds 67h address-size support + RM0 66h data-width subset |

**Why 386 cannot yet reuse every 16-bit native block:** Existing generated operations often write a full 32-bit ARM register when updating a guest 16-bit register. This is valid for 286 because only the low 16 bits matter, but incorrect for a 386 because 16-bit operations must preserve bits 16–31 of EAX–EDI. The CPU model flag already separates the paths; once the 386 JIT preserves those high halves and handles the prefix semantics, individual safe 16-bit Thumb-2 lowerings can be reused. We do *not* discard the existing fast JIT.

## Newly implemented

- `67h` 32-bit ModR/M effective addresses: base + scaled index + signed displacement with 32-bit wrapping arithmetic.
- SIB scale 1/2/4/8, special `index=4` (no index), `mod=0 base=5` (no base/disp32), and `mod=0 r/m=5` (disp32).
- 32-bit ESP/EBP effective-address defaults to SS; otherwise DS. Segment override prefixes retain their meaning.
- `67h` memory operand forms: MOV byte/word, TEST, XCHG, ADD/OR/ADC/SBB/AND/SUB/XOR/CMP, group-1 immediate `80/81/83`, MOV immediate `C6/C7`, and LEA.
- `66h+67h` DWORD memory forms of these operations, plus 32-bit MOFFS `A0..A3` with the right operand width.
- Correct upper-half preservation on 8- and 16-bit register writes, including a redundant `66h` before a byte opcode.
- `LEA` produces a 32-bit offset without reading memory or performing a segment-limit check.
- Real-mode 64 KiB segment-bound checks on 67h memory accesses. Unsupported out-of-limit accesses return `B86_UNSUPPORTED` instead of silently wrapping them to 16 bits; architecturally correct #GP/#SS delivery is **future work**.

## Still missing

- `0F` extended 386 instruction set, FS/GS, 32-bit string/shift/control instructions, address-size semantics on all remaining legacy opcodes, 32-bit protected-mode segments/paging/interrupt gates, unreal mode, 486-only behavior.
- On 386, unsupported cases return status `B86_UNSUPPORTED` (5), **not** a guest #UD/#GP. Real exception delivery will follow later.
- No 386 native Thumb-2 code; 386 is interpreter-only and not performance-ready.
- No added JIT SRAM allocation; new helper routines use `B86_COLD` flash placement. A final Pico build is required to confirm link-time SRAM and flash totals.

## Install (after RM0)

Extract **all files** in the ZIP to `C:\blitzBUS`. RM0 (`bb_386_rm0_v1.py`) must already be installed. Do not restore RM0 before installing RM1.

```powershell
cd C:\blitzBUS
python .\bb_386_rm1_v1.py selftest
python .\bb_386_rm1_v1.py probe
python .\bb_386_rm1_v1.py apply
python .\bb_386_rm1_v1.py verify
```

RM1 backs up and edits only:

- `C:\blitz86_v2\src\interp.c`
- `C:\blitz86_v2\tests\bb_386_rm0_smoke.c` (changes the obsolete 67h-unsupported test)

It creates:

- `C:\blitz86_v2\src\i386_rm1.inc`
- `C:\blitz86_v2\tests\bb_386_rm1_smoke.c`

It **does not modify** `jit.c`, `be_t2.c`, `backend.h`, `b86.h`, the production memory configuration, or earlier experiment backups. The exact-byte backups are in `C:\blitzBUS\.bb_386_rm1_v1_backup`.

**Layer restore order:** If you need to go backwards, restore RM1 first, then RM0, then earlier RCL/RCR experiments. Older installer `verify` commands can fail while newer layers intentionally modify the same files; this is expected and not source corruption.

## Host correctness test

Compile from the actual local `C:\blitz86_v2` checkout. Example with GCC/Clang in WSL:

```bash
cd /mnt/c/blitz86_v2
mkdir -p build
gcc -O2 -Wall -Wextra -Iinclude src/interp.c tests/bb_386_rm0_smoke.c -o build/bb_386_rm0_smoke
gcc -O2 -Wall -Wextra -Iinclude src/interp.c tests/bb_386_rm1_smoke.c -o build/bb_386_rm1_smoke
./build/bb_386_rm0_smoke
./build/bb_386_rm1_smoke
```

Expected:

```
BB386 RM0 PASS — 386/286 interpreter smoke tests
BB386 RM1 PASS — 67h/66h+67h SIB, segments, wrap, LEA, flags, limits, 286 isolation
```

**Development validation performed:** Reversible installer LF/CRLF and byte-identical restore checks, plus GCC compilation and both C smoke executables against a standalone interpreter-stub environment. This is useful for validating the new decoder/helper logic, but **not a successful full upstream `src/interp.c` build**. Run the commands above against your source to verify integration.

## Pico regression: retain 286 mode

```powershell
cd C:\blitzBUS
$env:BB_CPU = "286"
$env:BB_CODE_KB = "232"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180
```

Use your existing other BB_* settings. From DOS `C:\BENCH`, run `RCXTEST`, `T2ECPU`, `3DBENCH`. Baseline targets: PASS 64/64, checksum 8642, 58.8, and a successful 512 KiB SRAM link. If the linker fails, do not reduce the 232 KiB cache for production just to accommodate this feature; investigate section placement.

## Restore only RM1

```powershell
cd C:\blitzBUS
python .\bb_386_rm1_v1.py verify
python .\bb_386_rm1_v1.py restore
python .\bb_386_rm0_v1.py verify
```

`restore` refuses to overwrite files changed after installation, and restores their exact original bytes.

## Follow-on CPU steps

1. Broaden all 386 address-size effects (string loops, LOOP/JCXZ family, full shift group, stack addressing), then validate all combinations of `66h/67h`.
2. `0F`-map additions (MOVZX/MOVSX, SETcc, near Jcc, bit scans/test, SHLD/SHRD), 32-bit control transfers and EFLAGS.
3. Build architectural exceptions, descriptors, 286 and 386 protected modes and paging; extend guest PSRAM memory to support DPMI/extender execution.
4. Native 386 JIT: reuse Thumb-2 lowerings when *proved safe* under 32-bit register preservation, emit new DWORD lowerings in flash-generated code, keep the cache fixed at 232 KiB.
