# blitz86 RM3 — FS/GS + 32-bit near control flow (386 real mode)

**Prerequisites:** Existing RM0, RM1, RM2 and the **RM2 SRAM-to-flash relocation fix** installed. This milestone layers on top of your confirmed **58.8 / 232-KiB JIT cache / 99.54% SRAM** configuration. It is **not** a 386 protected-mode implementation and is **not yet a Descent-capable firmware**.

## Files

This is **complete new C source and a reversible installer, not a Git patch**.

- `bb_386_rm3_v1.py` — `selftest`, `probe`, `apply`, `verify`, `restore`; SHA-256-backed backups; refusal on unexpected anchors.
- `i386_rm3.inc` — all new 386-only instruction helpers explicitly `noinline`, `cold`, and in `.text.bb386_flash`.
- `bb_386_rm3_smoke.c` — host tests compiled against your *real* `src/interp.c`.

Only three existing source files are edited: `include/b86.h`, `src/interp.c`, and `src/i386_rm1.inc`. No files under the Thumb-2/AArch64 emitter or JIT implementation change. The 286 CS/DS/SS/ES numerical values and their structure offsets remain unchanged; a **four-byte `seg386[2]`** state field is appended to `B86Cpu` for FS/GS.

## New supported 386 real-mode operations

| Area | Instructions / behavior |
|---|---|
| FS/GS selectors | `MOV FS/GS,r/m16`, `MOV r/m16,FS/GS`; `66 MOV r32,Sreg` zero-extension for register destinations |
| Segment prefixes | `64h` FS / `65h` GS with selected 16-bit memory operations, RM1 `67h` addressing and RM2 extended `0F` memory operations |
| FS/GS stack | `0F A0/A1/A8/A9`: PUSH/POP FS/GS in word or (with `66h`) dword operand widths |
| Far-pointer data loads | `0F B4/B5`: LFS/LGS m16:16 or m16:32, including `67h` addressing |
| 32-bit near flow | `66 E8`, `66 E9`, `66 C2`, `66 C3`, `66 FF /2,/4` |
| 32-bit stack | `66 FF /6` PUSH r/m32; `66 60` PUSHAD, `66 61` POPAD, `66 C9` LEAVE; limited `66 9C/9D` PUSHFD/POPFD |
| Real-mode safety | Reject near EIP > FFFFh, cross-limit data accesses and unimplemented instruction forms via `B86_UNSUPPORTED`; do not silently truncate to a different instruction |
| Model guards | All new paths require `B86_CPU_386`; existing 16-bit Thumb-2 translations remain model 286 |

**Deliberate limitations:** FS/GS memory forms not covered by RM1/RM2 or RM3's byte/word/DWORD MOV, immediate MOV, and TEST subset return unsupported. The selector cache/protected-mode descriptor base and limits are not implemented, so FS/GS uses `selector << 4` and real-mode 64 KiB limits. CALL gates, far 32-bit CALL/JMP/RET, 32-bit SS stack-address attributes, TSS, paging, full EFLAGS/privilege semantics, I/O privilege checks and x87 remain unimplemented. `PUSHFD/POPFD` currently handle the low 16 flag bits only. Unsupported cases are not architectural #GP/#SS exceptions yet. Do **not** enable 386 DOS emulation as the system default.

### Install (PowerShell)

Extract **all three files** from the ZIP into `C:\blitzBUS`. Do not restore RM0/RM1/RM2 or the flash-relocation fix first.

```powershell
cd C:\blitzBUS
python .\bb_386_rm2_flash_sram_v1.py verify
python .\bb_386_rm3_v1.py selftest
python .\bb_386_rm3_v1.py probe
python .\bb_386_rm3_v1.py apply
python .\bb_386_rm3_v1.py verify
```

The RM3 backup lives in `C:\blitzBUS\.bb_386_rm3_v1_backup`. Previous installers may report **expected SHA mismatches while RM3 is active** because RM3 intentionally extends their modified source files. To restore, always undo RM3 first:

```powershell
python .\bb_386_rm3_v1.py verify
python .\bb_386_rm3_v1.py restore
python .\bb_386_rm2_flash_sram_v1.py verify
```

### Test actual interpreter source on a host

Using WSL/GCC (or equivalent installed host GCC/Clang):

```bash
cd /mnt/c/blitz86_v2
mkdir -p build
gcc -O2 -std=c11 -Wall -Wextra -Iinclude \
    src/interp.c tests/bb_386_rm3_smoke.c \
    -o build/bb_386_rm3_smoke
./build/bb_386_rm3_smoke
```

This performs **70 total assertions**, including the old 286 execution test. RM1 and RM2 reference tests can also be run against the same source checkout.

**Validation before delivery:** RM3's 69 386-only assertions passed with GCC and Clang (including AddressSanitizer / UndefinedBehaviorSanitizer), using a synthetic integrated RM0+RM1+RM2+RM3 interpreter harness. The RM1 and RM2 smoke programs also passed in that harness. The reversible installer completed its LF/CRLF and exact rollback selftests. **The true modified upstream interpreter and your RP2350 firmware have not been compiled or executed here**; report their real outcomes, not synthetic outcomes, as project validation.

### Check 286/Pico performance and SRAM after installing

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

In `C:\BENCH` run `RCXTEST`, `T2ECPU` and `3DBENCH`. Target results: **64/64, checksum 8642, 58.8**. Check the Pico linker output: `RAM < 524,288 B`, **code cache still 232 KiB**, and no stack/heap overlap. Do not claim the SRAM budget is proven until it links on your build.

### Next architecture milestones

1. Expanded 386 real-mode opcode coverage, exceptions, and PIC/IRQ integration, tested on the RP2350 interpreter (not just a host harness).
2. Protected-mode descriptor caches and access rights, exception delivery, CPL/DPL, 32-bit CS:EIP and SS:ESP semantics.
3. Larger PSRAM-backed guest physical memory and DOS extender / DPMI-compatible execution for Descent.
4. Selective Thumb-2 native lowering for 386 instructions **after** 32-bit and upper-register preservation equivalence tests.

The current 286 Thumb-2 engine and its allocated 232 KiB executable cache remain the regression baseline.
