# blitz86: 80386 real-mode milestone 0 (experimental)

This package **implements code** in your existing `C:\blitz86_v2` working tree, with byte-exact backups and restore. It does not replace your local files wholesale with stale GitHub copies, nor does it use Git patches.

## Important preservation guarantees

* The existing 8086/186/286 code paths remain the baseline; the Pico keeps `BB_CPU=286`.
* Native memory RCL/RCR and eager unchaining are retained in the originals the installer backs up.
* On `B86_CPU_386`, the JIT entry point uses the interpreter rather than attempting to execute 16-bit-only translated code. This mode is intentionally slow until the 32-bit JIT is developed.
* The `src/i386_rm0.inc` implementation is placed in flash (`B86_COLD`); no 386 metadata allocations or enlarged JIT SRAM buffer are added.
* New opcode support is deliberately **partial**. `B86_UNSUPPORTED` (5) reports valid-but-unimplemented 386 forms without executing them as 16-bit instructions.

## Scope of this slice

Supported in **386 real mode with default 16-bit addressing**:

* 66h 32-bit GPR immediate move (`B8`-`BF`), register/memory moves (`89`, `8B`, `C7 /0`, `A1`, `A3`)
* 66h 32-bit integer ALU operations (ADD, OR, ADC, SBB, AND, SUB, XOR, CMP), including ModR/M and `81`/`83` immediate groups
* 66h INC/DEC GPR32, PUSH/POP GPR32, PUSH imm32/imm8 (sign extended)
* 66h CWDE, CDQ and NOP
* Unprefixed 16-bit instructions preserve the *upper* halves of EAX..EDI in the 386 interpreter wrapper
* 16-bit stack addressing remains SS:SP (push/pop 32-bit changes SP by 4)

**Not supported in this slice:** 67h address-size overrides, FS/GS, 386 0F opcodes beyond already implemented 286 forms, 386 control registers, 32-bit shifts/string/control transfers, selector/protected-mode semantics, paging, exception-fault limits, or a 32-bit JIT. A full 386/486 executable will not run yet.

## Install

Extract all files from the ZIP to `C:\blitzBUS`. Leave `bb_rcx_mem1_ab_v1.py` set ON, eager unchaining ON, and `BB_CPU=286` for the normal Pico regression.

```powershell
cd C:\blitzBUS
python .\bb_rcx_mem1_ab_v1.py verify
python .\bb_deadstub_unchain_ab_v2.py verify
python .\bb_386_rm0_v1.py selftest
python .\bb_386_rm0_v1.py probe
python .\bb_386_rm0_v1.py apply
python .\bb_386_rm0_v1.py verify
```

The installer edits exactly `include/b86.h`, `src/interp.c`, `src/jit.c` in `C:\blitz86_v2`, and adds `src/i386_rm0.inc`, `tests/bb_386_rm0_smoke.c`. Source backups and SHA-256 manifest are in `C:\blitzBUS\.bb_386_rm0_v1_backup`.

**Do not run the older RCL/RCR installer's verify, toggle, or restore while this new layer is active.** That installer owns an exact hash of jit.c from before the new 386 edits. Restore the 386 layer first, then use its commands.

## Host correctness test

If `gcc` or `clang` is available on your host (e.g. WSL, MSYS2), compile **your updated complete interpreter** and the new smoke test:

```bash
cd /mnt/c/blitz86_v2     # WSL example; use C:/blitz86_v2 in a Windows shell
mkdir -p build
cc -O2 -Wall -Wextra -Iinclude src/interp.c tests/bb_386_rm0_smoke.c -o build/bb_386_rm0_smoke
./build/bb_386_rm0_smoke
```

Expected:

`BB386 RM0 PASS — 386/286 interpreter smoke tests`

This checks upper-register preservation across 16-bit instructions, 32-bit arithmetic and flags, 32-bit memory moves, stack operations, an explicit unsupported status, and unchanged 286 behavior.

## Pico build regression (still 286!)

Keep **all** current settings, including `BB_CODE_KB=232`, `BB_CPU=286`, eager unlink ON, memory RCL/RCR ON. Rebuild with your existing `scripts\bb_live_run.ps1`, then run `RCXTEST`, `T2ECPU`, and `3DBENCH`. Expected baseline is 64/64, checksum 8642, and 58.8, respectively. A compiler/linker failure should be investigated before any flash.

Do not enable `BB_CPU=386` in blitzBUS yet: the embedding UI/parser is deliberately not changed by this milestone, and many instructions/memory features are still missing.

## Restore

```powershell
cd C:\blitzBUS
python .\bb_386_rm0_v1.py verify
python .\bb_386_rm0_v1.py restore
python .\bb_rcx_mem1_ab_v1.py verify
python .\bb_deadstub_unchain_ab_v2.py verify
```

If you intentionally edit one of the patched source files while the layer is installed, restore will refuse to overwrite your edits. Back them up and reconcile manually rather than forcing a replacement.

## Next slices

1. Extend the interpreter with 67h 32-bit effective addressing, ModR/M SIB and displacement decoding, and address-dependent segment selection.
2. Add remaining 386 real-mode instructions: MOVZX/MOVSX, 0F escape, shifts/bit tests, PUSHFD/POPFD, and 32-bit near control transfer semantics, with generated differential tests.
3. Implement segmentation/descriptor checks and mode transitions in the reference interpreter, including the remaining 286 protected-mode functionality.
4. Add extended memory / DOS extender integration; Descent also needs a newer DOS environment than the current DOS 2.00 boot.
5. Design a 32-bit Thumb-2 translation scheme with *constant* SRAM cache size, keeping cold code/metadata in flash and PSRAM.

This is a real first implementation, not complete 386 support. The synthetic host C smoke and installer self-tests must not be mistaken for a verified Pico firmware build.
