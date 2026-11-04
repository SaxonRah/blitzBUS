# blitzBUS / blitz86 todo list

Status as of 2026-11-04. See `ROADMAP.md` for the goals and `COMPAT.md` for the
compatibility matrix.

## 1. 3DBench speed (now 38.4, target 70+)

Profile at 240 KB real-mode cache: 36% translated code, about 22% interpreter,
5% lazy flags, about 5% USB console input polling, about 4% interrupt handling.

- [x] Reduce USB console input polling during programs (`blitzbus_poll_throttle_v1`:
      38.4 → 40.0)
- [x] Teach the harness to load programs above 64 KB like `LOADFIX`, so
      3DBench runs there (`LOADFIX=1`)
- [x] INT fast path in the real-mode JIT (`blitz86_int_fast_v1`); correct, but the
      `INT 16h` flood was 3DBench's title screen, not the benchmark
- [x] Ruled out: VGA retrace (70 Hz made no difference; rolled back), timer chain
      into DOS (3DBench's handler doesn't chain; the "DOS time" was its load phase)
- [ ] Note: the 70+ score was under microDOS (DOS 2 path, BIOS/DOS in C on the
      host), today's 40 under real DOS 6.22: different environments, accepted
- [ ] Count which instructions the real-mode JIT leaves to the interpreter
      (about 22% of the time)
- [ ] Translate the most frequent of them natively, or move their interpreter
      path back into SRAM
- [ ] Check the self-modifying-code detections (about 8,000 per 10 s): data and
      code sharing 64-byte lines?

## 2. Real-mode timer interrupt (IRQ0)

`BB622_IRQ0_AB_DISABLE 1` (a precaution from the DOS 6.22 bring-up) kept every
real-mode program with its own INT 8 handler from getting ticks. Patched by
`blitzbus_rm_irq0_v1` (3DBench: 00.0 → 35.7).

- [x] Watch `bb_rm_irq0` for stability: DOS, 3DBench, Descent (987 M instructions,
      120 Hz timer delivered, no faults; Descent 101.7 s/100 frames, within noise)
- [ ] Commit the local `bb_live.c` (`BB622_IRQ0_AB_DISABLE 0`, polling throttle) to the
      repository, so it's the default

## 3. SRAM split between real and protected mode

Real-mode programs need a large real-mode cache (3DBench: about 232 KB or
more); DOS/4GW and DJGPP programs need the protected-mode hot tier. Both share
the same SRAM, and today the split is fixed at build time.

- [x] Short term: two build profiles (`scripts\bb_profile.ps1 pm|rm`)
  - Real mode: `BB_PJ_HOT_KB 0`, `BB_PM_RAM 0`, `BB_CODE_KB 240`
  - Protected mode: `BB_PJ_HOT_KB 91`, `BB_CODE_KB 128`
- [ ] Long term: a shared SRAM pool, assigned at runtime to whichever JIT is
      active
  - [x] Design: one memory area, two code caches, eviction on handover
        (`DESIGN_SRAM_POOL.md`)
  - [ ] Real-mode JIT: cache in the pool
  - [ ] Protected-mode JIT: hot tier in the pool
  - [ ] Handover on mode switch (DPMI host, DOS calls)
  - [ ] Tests: 3DBench and Descent each with a full pool

## 4. Remaining performance levers (Descent, a few % each)

Measured on the Pico: protected mode is 99.8% native; runs average 179 guest
instructions; the remaining costs are spread thinly. Descent is at about 1 fps,
and the realistic headroom with this design is about 1.3–1.5x.

- [ ] 16-bit protected-mode code into the SRAM tier (`pm16-sram=0`, about 2–4%)
- [ ] Hot tier: lift the limit of 512 redirects, stop the threshold from
      climbing (about 3–5%)
- [ ] Cheaper checks on forward edges, `pj_stop` kept (about 1–2%, below the
      measurement noise)
- [ ] Inline reads (V122): off by default; revisit only if code size stops
      mattering (v2 thrashed the main buffer, v3 was 10–13% slower)

## 5. Compatibility pass (`COMPAT.md`)

- [x] Harness pre-screen of `dos_bench`
- [x] #UD for non-386 two-byte opcodes (`blitz86_386ud_v1`, CHKCPU)
- [x] Real-mode IRQ0 (`blitzbus_rm_irq0_v1`, 3DBench timing)
- [ ] Copy Doom and CHKCPU from `dos_bench` onto the SD image and run them on
      the Pico
- [ ] EXEPACK "Packed file is corrupt": DOS loads programs below 64 KB; fix
      the load address instead of requiring `LOADFIX`?
- [ ] Quake: FPU detection reports "no coprocessor" (FNINIT/FNSTSW, CR0.ET)
- [ ] CACHECHK: divide error after timer measurement, check on the Pico
- [ ] XMS: does the Pico's DOS load HIMEM.SYS? (Speedsys)
- [ ] DPMI 0506h/0507h/0A00h: answer as harmless no-ops?
- [ ] Further titles per extender family (DOS/32A, PMODE/W, more DJGPP)

## 6. Open bugs and shelved work

- [ ] V119 (flat `POP`/`MOV` ES/DS without block exit): crash in the Descent
      demo, cause unknown; shelved, rolled back
- [ ] Harness checkpoints, so long scenarios (Descent's demo) can be verified
      there

## 7. Documentation

- [ ] Commit `COMPAT.md` and the updated `ROADMAP.md`
- [ ] Clarify the x87 paragraph in the roadmap (which x87 path is actually
      active)
- [ ] Record the Descent measurements and conclusions in the repository

## 8. Roadmap: Pi Zero 2 W to AArch32

- [ ] Boot a hello-UART image in AArch32
- [ ] `start.S` for AArch32 (vectors, MMU, caches)
- [ ] Replace AArch64 inline assembly in `microdos_pi0w.c`
- [ ] DOS 2 on the interpreter, then the JIT with an allocator and cache
      maintenance
- [ ] Compare against the AArch64 numbers

## 9. Roadmap: native Thumb-2 compiler ("DOS for ARM")

- [ ] Choose the compiler (TinyCC is the lead candidate) by checking it
      against Descent-era C
- [ ] Versioned call table between native code and the emulated DOS
- [ ] Executable format and loader
- [ ] Protecting the emulator from faulty native code (MPU on the Pico)
- [ ] Section attributes for hot and bulk code (SRAM/PSRAM)
- [ ] First milestone: "hello world" compiled inside DOS, running natively
- [ ] Stage 0: the compiler as an x86 DOS program under blitz86
- [ ] Stage 1: the compiler compiles itself to Thumb-2
