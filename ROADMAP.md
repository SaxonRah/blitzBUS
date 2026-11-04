# blitzBUS roadmap

## Goal

A DOS handheld for music, games and demoscene work on ARM:

- **Run existing DOS software fast.** DOS 6.22 and DOS/4GW programs (Descent
  today; Quake as a stretch) through the blitz86 translator. Target: match or
  beat the fastest 486-class machine of the day, which needs roughly 3 host
  instructions per guest instruction on real code, not only on tight loops.
- **Build new software inside DOS, natively.** A compiler running under
  blitzBUS that emits Thumb-2, so software built on the device runs as native
  code at full speed: "DOS for ARM".

## Where things stand

| Project | Role |
|---|---|
| blitz86 | x86 core: interpreter, translator (Thumb-2 and AArch64 backends), 386 protected-mode tier (PJ). Runs DOS/4GW programs. |
| blitzBUS | RP2350 board glue and DOS 6.22 boot from SD images; settings and run scripts. |
| microDOS | firmware build tree and the original recompilation/interpreter project (DOS 2 bring-up). |
| MicroRender / MicroWave | allocation-free 2D renderer and audio mixer (DOS, Pico 2, desktop). |
| MicroConsole | handheld integration on Pico Plus 2: LCD, I2S audio, SD, controls; FastDoom runs natively. |
| pico-uart-bridge-pi02w | Pico as UART console and reset controller for Pi Zero 2 W bare-metal work. |

Two software paths already exist: DOS binaries through the blitz86 translator,
and source-ported games (FastDoom, MicroRender demos) compiled natively on a
PC. The on-device compiler is the third path and the one that closes the loop.

## Decisions

- **Native target is Thumb-2 only.** It is the one ISA shared by the RP2350
  (Cortex-M33) and the Pi Zero 2 W's A53 in AArch32. Supporting a second native
  ISA in the toolchain is out of scope.
- **The Pi moves from AArch64 to AArch32.** Today the Pi path is AArch64 and
  has only run DOS 2. Moving it to 32-bit lets it run the same Thumb-2 translator
  backend and the same native exes as the Pico.
- **The AArch64 backend stays, as a test target.** Keep `be_a64.c` in the
  fuzz and silicon-vector matrix under `qemu-aarch64` so it does not rot. It is
  not a hardware or toolchain target. A native A64 compiler backend is a
  later, additive job (new backend, recompile; native exes are not portable
  across ISAs).
- **The handheld is the Pico Plus 2.** The Pi Zero 2 W is a fast development
  host and a hardening target for blitzBUS, not the shipping hardware.

## Now: compatibility pass

Descent under the blitzBUS DPMI host is stable (virtual memory with SD swap,
direct IRQ delivery, sound and music) but CPU-bound at about 1 frame per
second; see "Performance goals". Before more speed work, map what runs: the
`dos_bench` pack (PhilsComputerLab, 18 programs) covers real mode, DOS/4GW,
DJGPP/CWSDPMI, VGA and VESA. Procedure, matrix and predictions are in
`COMPAT.md`.

1. Run the matrix with `BB_DPMI=1`; re-run failures with `BB_DPMI=0` to tell
   host problems from CPU problems.
2. Record the cause of each failure (BIOS function, DPMI function,
   instruction) in `COMPAT.md`.
3. Fix by reach: what unblocks the most programs first. Likely candidates:
   DJGPP on the DPMI host (Chris's 3D, Quake), CPU-detection answers, clean
   failure instead of hangs for VESA requests.
4. Add the DOS games on the SD image (Descent, Doom) and further titles per
   extender family once the pack is green.

## Next: Pi Zero 2 W to AArch32

The existing Pi bring-up lives in `microDOS/pi0w/`: `config.txt`
(`arm_64bit=1`, `kernel8.img`, mini UART), `start.S` (about 300 lines: EL2
entry, page tables, cache enable and maintenance), `microdos_pi0w.c` (about 950
lines, about 10 inline-asm sites for system registers, `nop` and `wfe`), and
`blitz86_pi_target.cmake`, which links only `interp.c` (the translator still
needs an allocator and an executable arena on the Pi).

1. Boot a hello-UART image in AArch32 through the existing build, reset,
   rpiboot and UART capture loop: `arm_64bit=0` and a 32-bit kernel name in
   `config.txt` (verify against the actual rpiboot flow).
2. Rewrite `start.S` for AArch32: entry mode, vectors, MMU (identity map,
   cacheable RAM, device-mapped peripherals), caches, and a decision on
   unaligned access.
3. Replace the AArch64 inline asm in `microdos_pi0w.c` with AArch32
   equivalents (CP15 instead of `SCTLR_ELx`, `CNTFRQ` and so on).
4. Bring up DOS 2 on the interpreter again, then link `jit.c` and `be_t2.c`
   with an allocator, an executable arena and cache maintenance after code
   writes (clean D-cache, invalidate I-cache).
5. Re-run `hardware pi` and `jit-hardware pi` with Thumb-2 and compare against
   the recorded AArch64 numbers (for example regmix 712 MIPS, loop 333).
6. Tag the AArch64 Pi code before removing it.

## Future: a native Thumb-2 compiler for DOS

- **Compile in DOS, run natively.** A compiler running under blitzBUS that
  emits Thumb-2 code, plus a small loader and calling convention, so software
  built inside DOS runs as native code at full speed instead of going through
  blitz86. The same exe format and call table serve the Pico 2 and the Pi.
- **Bootstrap in two stages.** Stage 0: build the compiler as an ordinary x86
  DOS exe and run it under blitz86. Stage 1: compile the compiler with itself
  to Thumb-2 and run it natively.
- **Soft limits.** Build a "Pico profile" into the compiler: fixed-size arena,
  caps on symbol table, function and translation unit size, and track the
  compiler's own code and RAM size so it cannot quietly outgrow the Pico while
  development happens on the faster Pi.
- **Later: compile DOS itself natively.** Build the DOS kernel and core
  components to Thumb-2, so only legacy x86 programs are translated.
- **Compiler choice (open).** A single-pass compiler that writes executables
  directly (TinyCC is the lead candidate) means one codebase to retarget to
  Thumb-2. The alternative (cproc with QBE, or chibicc) gives cleaner code but
  also needs a Thumb-2 assembler and a linker. Decide after checking each
  against the language level of the target source (Descent-era C).
- **Questions to settle first:**
  - the interface between native code and the emulated x86 state (registers,
    memory map, interrupts, DOS calls), as a versioned call table passed in
    by the loader;
  - protecting the emulator from faulty native code (M33 MPU on the Pico, page
    permissions on the Pi);
  - where native code lives (SRAM vs PSRAM: the capacity and churn lessons from
    V105-V112 apply), so the compiler and linker need section attributes for
    hot and bulk code;
  - 64-bit math (`fixmul`/`fixdiv` via `SMULL`, plus the `__aeabi_*` helpers);
  - which compiler to adapt.

## Performance goals and open measurements

- **3 host instructions per guest instruction.** The `CHANGES.md` call-kernel
  numbers are 5.8 on Thumb-2 and 4.8 on AArch64 after the latest optimization,
  and tight register loops reach about 1.5 to 2.2. Whole-program ratios on
  Descent and 3DBENCH in protected mode are not recorded here yet. Measure them
  first, then set a per-program target.
- **Pick a reference 486 system** and compare frame rates on 3DBENCH and Descent
  against it, instead of comparing MIPS.
- **Descent, measured (2026-11-04).** About 1 fps in the demo with sound and
  music at 360 MHz (98-110 s per 100 frames). Core 0 during the demo: 44%
  native code (of which about 19 points are the JIT's shared stubs, mostly the
  memory trampoline), about 8% block lookups, 6% interpreter, 5% translation
  and SMC churn, the rest spread thinly. Window size barely matters: the cost
  is per frame (geometry, game logic, DOS/4GW, HMI sound), not per pixel.
  Sample-driven SRAM promotion (V120) doubled the SRAM tier's share to about
  10%; the remaining PSRAM block time is a long tail. Realistic remaining
  headroom with this design is about 1.3-1.5x (tier limits, lookups, inline
  memory access); a playable frame rate for Descent is out of reach on this
  hardware.
- **Quake needs an x87 FPU.** blitz86 has an experimental x87 path (two
  commits, 2026-10-24), built only with `B86_X87_EXPERIMENTAL`. Neither blitzBUS
  nor microDOS sets that flag, so the known-good firmware runs the
  absent-coprocessor mode from r61 (FPU instructions decoded and ignored).
  (To check: current DPMI-host logs show `[bb386-x87] c-executed=... D9:...
  DD:...` for Descent, so some x87 execution in C is active in today's
  build; confirm which path and update this paragraph.)
  What the experimental path has: exact 80-bit software arithmetic with
  round-to-nearest-even; register-form FADD/FSUB/FSUBR/FMUL/FDIV/FDIVR and their
  popping forms; FLD/FST/FSTP/FXCH ST(i); the seven constants; FCHS, FABS,
  FRNDINT; the FCOM/FUCOM/FTST compares; FNSTSW AX; FLD m32/m64/m80, FSTP m80,
  FILD m16/m32/m64, FIST/FISTP (and FISTTP, which a real 387 does not have),
  FLDCW/FNSTCW/FNSTSW m16; paging-rights checks, and PJ invalidation for x87
  stores. It runs in the C protected-mode path, not natively, and a rejected
  instruction leaves state untouched.
  Gaps before Quake: FST/FSTP m32/m64, memory-operand arithmetic, FSQRT, the
  transcendentals, #MF delivery for unmasked exceptions, silicon-vector or
  fuzz tests (none in `tests/` yet), and native lowering. The RP2350 has only
  single-precision hardware, so the precision policy is a design decision.
- **Idea to evaluate:** microDOS's `dosrecomp` turns known DOS binaries into
  portable C. The on-device compiler could, in principle, compile that output
  natively as a third speed path for existing exes.
