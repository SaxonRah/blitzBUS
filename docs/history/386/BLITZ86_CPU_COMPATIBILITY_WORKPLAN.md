# blitz86 — 186/286 completion and the path to 386/486

**Baseline:** Pico Plus 2, RP2350 at 300 MHz, 232 KiB executable native cache, eager unchaining ON, native memory `RCL/RCR` ON, 3DBench **58.8**. Do not reset any of these settings while introducing new CPU features.

**Scope:** Source-grounded review of the published `SaxonRah/blitz86` repository (`include/b86.h`, `src/interp.c`, `src/jit.c`, `src/be_t2.c`, `README.md`, as inspected 2026-10-13). **Local `C:\blitz86_v2` may have changes not yet published.** The supplied read-only audit checks that local copy; no assumption that published and local branches are byte-identical.

## 1. What is implemented already

| Generation | Interpreter | Thumb-2 JIT | Remaining work |
|---|---|---|---|
| 8086/8088 | Mature 16-bit baseline, documented silicon-vector validation | Extensive native lowering | Regression protection, unusual edge cases |
| 80186/80188 | `PUSHA`, `POPA`, `BOUND`, `PUSH imm8/16`, `IMUL r16,r/m16,imm`, `INS/OUTS` (including REP), `C0/C1` shifts, `ENTER/LEAVE`, five-bit count masking | Native `PUSH immediate`, `LEAVE`, selected shift-by-immediate and register count paths; memory `RCL/RCR by one` newly tested locally | Many 186 forms still use a single interpreter instruction; documented single `ENTER` vector has a missing memory input |
| 80286 | Selected `0F` system instructions (`SGDT/SIDT`, `LGDT/LIDT`, `SMSW/LMSW`, `CLTS`); exception/FLAGS/PUSH SP differences; numerous invalid-opcode checks | Interpreted when no native lowering; preserves compatibility | Real-mode word-crossing limit faults absent; **80286 protected mode absent** |
| 80386 | **No CPU model in published header**; 16-bit real-mode interpreter remains | No 386 decoding or native 32-bit guest semantics | Everything listed in §3 |
| 80486 | No model | No 486 native semantics | 486 features after 386 is correct |

Published README test records: 8086 61,600/61,600; 186 28,325/28,326 (one ENTER test-vector memory omission documented); 286 real-mode 94,427/94,427 interpreter, 83,809/83,809 JIT. These are **historical**, not current-run results.

**Important:** The fact that `B86Cpu.r[8]` uses `uint32_t` is *not* 386 execution support. In the current JIT the **upper halves are explicitly treated as garbage**; the interpreter's instruction pointer and addressing wrap to 16 bits, and 66h/67h are not decoded as 386 prefixes.

## 2. The SRAM rule

* **Executable SRAM stays 232 KiB.** CPU generation should not require increasing it.
* All new decode tables and lowerers should be **cold flash/XIP** by default (`B86_COLD` or an equivalent selective section). Avoid placing bulk 386 logic in existing `B86_HOT` routines.
* The interpreter dispatch stub may remain hot, but big 386-only instruction handlers belong in flash until profiling demonstrates a need to move small paths into SRAM.
* Grow translator metadata, block tables, decoder scratch, guest segment caches, and page metadata in **PSRAM**. Size limits and alignment must be verified before flashing.
* Preserve direct-mapped fast lookup and existing eager unchaining initially. Profile changes separately and keep an OFF rollback path.
* Stop any build that exceeds **522,240 bytes of 524,288 SRAM** (2,048 bytes minimum margin). The last known 232 KiB configuration used **521,860 bytes**, leaving **2,428 bytes**; the next large hot-code addition could fail to link.
* New 386/486 code may increase firmware FLASH substantially — acceptable, but keep an eye on performance if execution shifts toward XIP-heavy paths.

## 3. Proposed engineering milestones

### M0: Close the baseline; do not confuse native coverage with CPU correctness

1. Keep 186/286 instruction semantics already implemented in the reference interpreter.
2. Rerun existing 8086, 186, and 286 vector suites against `C:\blitz86_v2`; document command lines and results.
3. Add a **forced-native** RCL/RCR test path; current `RCXTEST PASS 64/64` may run cold cases in the interpreter.
4. Investigate the historical `ENTER` mismatch by checking whether the test vector omitted a stack word before changing the code.
5. Freeze a git commit with 58.8, checksum 8642, 232 KiB, no dead-stub exits.

Do **not** spend another full cycle tuning cache churn without evidence of user-visible improvement. Existing later-interval counts (up to 1,399 evicted blocks and 1,099 observed retranslations) establish room for improvement, not a blocker to ISA work.

### M1: First genuine 80386 — interpreter correctness before native lowering

Design the CPU state and default widths without changing behavior for 8086/186/286:

* Add explicit `B86_CPU_386` and `B86_CPU_486` models, gated behind a new test/feature toggle until handlers are complete. Do not silently treat them as 286.
* GPRs become architecturally **32-bit** for 386+; 16-bit writes preserve upper halves, 8-bit operations preserve the other bits; preserve the old fast 16-bit register scheme for earlier models.
* Add architectural EIP/EFLAGS and segment selectors plus **hidden descriptor caches**: base, limit, access/type, D/B size flags.
* Add operand-size `66h` and address-size `67h`, *independently* of the CS default (`D` bit). Handle 32-bit ModR/M/SIB/displacements for address size 32, 32-bit stack pointer mode, near/far transfers, and sign extension.
* Implement 386 `0F` map incrementally: near Jcc, SETcc, MOVSX/MOVZX, PUSH/POP FS/GS, LFS/LGS/LSS, BT/BSF/BSR family, SHLD/SHRD, IMUL variants; honor `#UD` for unsupported instructions.
* Build host differential tests for width transitions (`AL`/`AX`/`EAX`), prefix permutations, EIP wrap, flags, ModR/M+SIB, and stack effects. This becomes the 386 reference oracle.
* Initially run 386 instructions through the interpreter. Add Thumb-2 lowering after the oracle passes; **no need to enlarge SRAM** to obtain basic instruction support.

### M2: 386 protected mode and extenders

* Correct `CR0.PE` transitions, selector validation, GDT/LDT descriptor loading, access/limit/type checks, CPL/RPL/DPL, gate/trap/task distinctions as needed, and fault vectors/error codes.
* 16-bit and 32-bit code segments, stacks, interrupt gates, `IRET`, `RETF`, `CALLF`, descriptor cache invalidation, privilege transitions, and mixed-mode return to DOS.
* `CR0.PG` / 4 KiB paging **only when the target extender requires it**; begin with no-paging flat 386 protected mode for simpler tests.
* Add protected-to-real-mode call bridging and the extender's DOS/BIOS interrupt path; test separately from game rendering.
* Reuse the same descriptor machinery for **80286 protected mode** where 286-specific semantics are needed, rather than writing a separate engine.

### M3: Guest RAM and DOS environment (also required for Descent)

Descent's manual states a **386-33, 4 MB RAM, DOS 5.0+** minimum; 486-33 / 8 MB is recommended. `C:` already mounts the installer image, but currently the boot reports **MS-DOS 2.00** and **1088 KiB guest memory**. These are distinct blockers even after 386 instructions work.

* Design a PSRAM memory map providing at least **4 MiB guest physical memory**, including low memory, VGA/BIOS holes, and extended memory. Validate the 8 MiB PSRAM layout, all existing allocations, and the program's shadow/SMC metadata before changing `B86_MEM_BYTES`.
* Current guest memory is directly allocated as a 1 MiB+HMA 16-bit window. Expanding that array alone is **not enough** for a 386 address space, segmentation, or paging.
* Supply DOS 5-compatible runtime/services and the necessary HIMEM/XMS/VCPI/DPMI pathway selected by the actual target executable. Determine the **specific extender/loader** from the user's Descent installation rather than assuming a DOS/4GW executable.
* Use the existing SD `C:`/`B:` path, but test 32-bit DOS extender file I/O, program loading, memory allocation, and BIOS video services.

### M4: 486 subset then speed up hot native 386 blocks

* Keep 486 mode separate; add `BSWAP`, `CMPXCHG`, `XADD`, `INVD`/`WBINVD` treatment and any model-specific exceptions required by tests. CPUID availability is stepping-dependent and should not be assumed for every 486.
* Run 386 protected-mode smoke tests and Descent's loader before translating hot 32-bit inner loops. Where the JIT falls back, it should still be correct.
* Refine hot 386 Thumb-2 paths while preserving 232 KiB cache, same SRAM fixed budget, and legacy 58.8 regression score.

## 4. Immediate work order

1. **Now:** run `bb_cpu_readiness_v1.py` against the local checkout, record local feature indicators and linker memory headroom.
2. **Then:** freeze the current known-good RCL/RCR-ON baseline and rerun existing 186/286 host tests.
3. **First coding milestone:** CPU-state width representation and `66h`/`67h` interpreter decode, model-gated, with host tests that demonstrate old 8086/286 behavior is unchanged.
4. **First game-specific proof:** run a tiny 386 32-bit code-segment test through a minimal protected-mode GDT. Do *not* begin with Descent's full loader.
5. **Integration proof:** boot a DOS 5+ environment with 4+ MiB accessible guest RAM, then run the particular Descent extender and the game.

## 5. Commands to run now

```powershell
cd C:\blitzBUS
python .\bb_rcx_mem1_ab_v1.py set on
python .\bb_rcx_mem1_ab_v1.py verify
python .\bb_deadstub_unchain_ab_v2.py verify
python .\bb_cpu_readiness_v1.py selftest
python .\bb_cpu_readiness_v1.py audit
```

For a linker budget check, save a full build transcript including the memory-region report, then:

```powershell
python .\bb_cpu_readiness_v1.py audit --log .\logs\full-build-transcript.txt
python .\bb_cpu_readiness_v1.py guard --log .\logs\full-build-transcript.txt
```

`guard` returns nonzero if a memory report is missing or SRAM headroom is below 2 KiB. The script **does not modify local source files or firmware**.

### References

* Source: `https://github.com/SaxonRah/blitz86/blob/main/README.md`
* Source: `https://github.com/SaxonRah/blitz86/blob/main/src/interp.c`
* Source: `https://github.com/SaxonRah/blitz86/blob/main/src/jit.c`
* Source: `https://github.com/SaxonRah/blitz86/blob/main/include/b86.h`
* Descent manual: `https://www.dosdays.co.uk/media/games/descent/Descent-Manual.pdf`
