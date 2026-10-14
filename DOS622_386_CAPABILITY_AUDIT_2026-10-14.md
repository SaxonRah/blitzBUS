# blitzBUS DOS 6.22 + 386 Compatibility Audit

**Audit:** 2026-10-14. **Objective:** eliminate one-BIOS-call-per-flash development and get a complete DOS 6.22 + live 386/DOS extender compatibility target.

## Source of truth and limits

- Live hardware result: `Pasted text(20261014-094332).txt` (the user's latest boot test).
- Public repo inspected: `SaxonRah/blitzBUS`, default branch latest visible at commit `a0e2dbf756d3c9c3d8cfd6f43f08d2a6afd90298` (`pre-622`, 2026-10-14). User's installed V1/V2 patches may be **newer than the public commit**. The actual log is the authority on runtime observations.
- Relevant public files: `src/bb_live.c`, `src/bb_386_pico_probe.inc`, `src/bb_vga.c`, `src/bb_dos622_bios.inc`, `src/bb_dos622_hdd_bios_v1.inc`, `src/bb_pit.h`, `src/bb_irq.h`, `sd_boot/bb_sd_boot.c`, `scripts/bb_live_run.ps1`.
- **No claim of complete BIOS, MS-DOS 6.22 installation, or 386 execution is supported yet.**

## Verified from last capture

| Area | Observed | Important limitation |
|---|---|---|
| Firmware | Pico firmware compiles, flashes and runs on 300 MHz RP2350 with 8 MiB PSRAM | Native RAM ~515,060 / 524,288 bytes used: 98.24%; limited headroom |
| DOS boot | Genuine DOS 6.22 floppy boot; `COMMAND.COM` and `A:\>` prompt; DOS directory works | **Still booting floppy**, not installed hard disk |
| Floppy A: | `DOS622.IMG` is read-only and readable as BIOS `DL=00h` | Setup floppy, no writes allowed |
| Floppy B: | Physical BIOS drive `DL=01h` announced; `B:\>DIR` displays volume `DESCENT1`, `INSTALL.EXE`, `DESCENT1.SOW` | Other disk swaps via existing B_DISK.TXT require later testing; B is read-only |
| Hard disk C: | `DOS622_HDD.IMG` available as BIOS `DL=80h`; CHS read/write and FAT16 partition found | `IO.SYS` and `MSDOS.SYS` on C: were **zero-byte placeholders** in earlier test; not proven bootable |
| Text graphics | `B800:0000` mirrored to LCD and serial, screen clears handled; BIOS 80x25 mode 03h | Console flooded by debug; palette and font/video queries incomplete |
| VGA graphics | Mode 13h 320x200 and DAC palette basis present | VGA memory planes/Mode X and full VGA registers not implemented; not demonstrated with Descent |
| Keyboard | ASCII input and BIOS key queue, VT function/navigation keys decoded and host USB CDC used | F-keys end-to-end only partially exercised; no full 8042 keyboard controller model |
| PIC/PIT | Models for PIT and master PIC present; port I/O shares host paths | **IRQ0 is explicitly suppressed in DOS6**; cannot call real PC timing complete |
| RTC/time | BIOS INT1Ah RTC; BDA tick emulation | RTC seeded from build date, not host real-time sync; guest IRQ timer bypassed |
| CPU model | Active `BB_CPU=286` shows `80286 (real mode)` | 386 smoke says `PASS 10/10` but uses separate CPU and restores memory: **not the running guest** |
| Memory | 640 KiB conventional DOS; 1088 KiB total backing, PSRAM | INT15h AH=88h reports **0 KiB extended**; Descent needs at least 4 MiB system RAM |
| Current stop | `B:\>install` executes, then `INT10h AH=12h BL=10h` at `11E2:862D` triggers safe stop | The EGA/VGA information query is currently missing |

### Exact latest stop

```
[bb622-missing-bios] unhandled INT 10 AX=1203 BX=0010 CX=0000 DX=0006 at=11E2:862D
[microDOS] guest stopped: fault
```

`AH=12h/BL=10h` is the EGA-information query (video color/mono, display memory size, feature/switch bits). Its `AL=03h` is **not** the subfunction selector. This should return a truthful EGA capability report and preserve the relevant BIOS register contract; merely setting `AX=1212h` would be inappropriate for this query. For baseline PC behavior, see IBM PS/2 BIOS Technical Reference and Ralf Brown's interrupt list.

## Compatibility target: two different stages

**Stage A: real MS-DOS 6.22 on an AT-compatible PC.** The OS itself is not a 386 protected-mode OS. The following are essential: accurate BIOS INT10, INT13, INT15, INT16, INT1A, INT11/12 services, PC equipment/BDA/IVT; floppy/HDD installation and boot; text/VGA functionality; standard keyboard; PIC/PIT/IRQ0; reliable FAT12/FAT16 writes/reads and error handling.

**Stage B: Descent and 32-bit DOS extenders.** Descent's manual specifies **386-33+, 4 MiB RAM, DOS 5.0+, VGA** (486 and 8 MiB recommended). This additionally requires a genuine 386-compatible guest CPU, 32-bit instructions and state, A20/8042 and extended RAM, protected-mode transitions, segment descriptors/GDT/IDT/TSS as required, exceptions, virtual memory as required by the chosen DOS extender, and compatible DPMI/VCPI/XMS interfaces or raw protected-mode support. SoundBlaster/AdLib, mouse and joystick come after startup and graphics. A boot-time 386 test **cannot** substitute for a live CPU model.

See Descent manual at `https://www.dosdays.co.uk/media/games/descent/Descent-Manual.pdf`, and open Watcom DOS/4GW references at `https://github.com/open-watcom/open-watcom-v2/blob/master/bld/redist/dos4gw/dos4gw.doc`.

## Stop the one-call-per-flash loop: implement subsystem suites

### Phase 0: console and observability — NOW

1. Run the generated clean host console `scripts/bb_live_run_dos622.ps1 -ConsoleView Screen` (created by bundled Python builder). This reconstructs a stable DOS 80x25 frame from existing `[bb622-screen]` records and **retains complete raw diagnostics in the original log**. Host-only change, no C code and no manifest rewrite.
2. `-ConsoleView Events` shows important successes and errors without screen rows; `-ConsoleView Raw` reverts to original console output.
3. Firmware follow-up: gate `[bb622-irq]`, `[bb622-ivt]`, `[bb-v62-vec]`, `[bb622-watch]`, repetitive `[bb-v23]`, `[bb-trace]` behind a single **DOS6 log level**. Recommended default: ERRORS+MILESTONES; DEBUG enabled by Ctrl+] or a selector. Host-only screen filtering does **not** save USB-CDC traffic or `printf` execution cost. Never delete raw diagnostic capability.
4. Maintain automated cases for `INT10 12/10`, VGA return-register checks, disk image integrity and host input; require host build and sample hardware trace before new patches.

### Phase 1: finish reliable DOS6 real-mode baseline

- **Video BIOS suite:** implement and test every actually required INT10 VGA/EGA query, mode 03h and 13h transition, character/scroll semantics, palette/font services, cursor, BIOS Data Area. Detect unsupported planar operations truthfully, rather than forging VRAM sizes. Current EGA query is first. Test built-in `CLS`, full-screen Setup, `INSTALL.EXE`, and eventually VGA framebuffer.
- **Disk suite:** carry BIOS CHS sectors across track/cylinder; keep DMA boundary checks; verify error AH/CF/AL semantics; handle disk-change and media detection and report accurate counts; test A, B and C separately. Preserve read-only floppy safety. Implement reliable Descent disk swaps without conflating A and B.
- **DOS installation:** complete real `SETUP` or `SYS` installation of nonzero system files and `COMMAND.COM`; use a validated MBR+FAT16 boot sector; add optional C: boot selection only after image is verified. Back up partially installed `DOS622_HDD.IMG` before writes.
- **Keyboard/PC control:** standard PC scan, 8042 status/data/commands, IRQ1 and shift flags as required; preserve host keyboard controls separately. Implement A20 toggling correctly, not just return unsupported.
- **Timer interrupt:** validate the master PIC remap/mask/ISR/EOI behavior and PIT ch0 IRQ0 delivery, BIOS INT08/INT1C, 18.2065 Hz baseline and CLI/STI/HALT cases; then remove the DOS6-only IRQ0 suppression.

### Phase 2: integrate true 386 guest and memory

- Provide one CPU state shared by interpreter, native translator, DOS interrupt hooks, memory model and breakpoint/fault reporter. Boot DOS6 on that CPU and then repeat real-mode tests.
- 32-bit register data, 0x66/0x67 operand/address-size prefixes, FS/GS, all relevant 386 instructions, correct flags and stack semantics, 386 exception/fault behavior.
- Protected-mode CR0.PE transitions, far jump/IRET/interrupt gates, descriptor privilege/present/limit semantics, GDT/LDT/IDT/TR, CPL and real/v86 transitions when required. Paging only if the target extender actually uses it; don't claim PSE/386+ functionality without tests.
- A20 gate + guest physical memory map with ≥4 MiB emulated memory; region-backed PSRAM with a measured memory allocation plan. Current boot has only 1088 KiB guest backing. Observe currently reserved PSRAM ~4,235,296/8,388,608 bytes. Adding multiple MiB guest memory requires deliberate remapping and test of all other PSRAM allocations.
- BIOS INT15h AH=88h / E801h (if implemented) must reflect memory actually backed and CPU-accessible. HIMEM.SYS/XMS and EMS/EMM386 interactions need explicit support or accurate refusal. Build a DOS extender conformance test independent of Descent.

### Phase 3: Descent application compatibility

- Install from the physical B: virtual floppy collection, verify all files and disk swapping, then launch real executable(s).
- Test VGA Mode13h and any game direct port access, latch/unchained planar modes when required, DAC and retrace semantics. Screen rendering speed should not regress the DOS interpreter.
- Bring up Sound Blaster DSP/OPL/FM, IRQ/DMA and mouse input after a known graphical menu boots. Game performance is a separate criterion from correctness.

## Recommended test matrix (one bundled test per subsystem)

| Test family | Examples | Exit criterion |
|---|---|---|
| BIOS video | mode03/13, INT10 12/10, 12/30, font, 0B, 13, palette/cursor/scroll | exact registers, BDA, framebuffer, all paths |
| BIOS floppy | A and B FAT12 root/cluster reads, EOT, drive geometry, read-only errors, disk swaps | checksum matches images, DOS `DIR` each |
| BIOS fixed disk | CHS boundaries, data verification, sync, media errors, FAT integrity | DOS FAT16 filesystem read/write; compare on host |
| Keyboard | ASCII, F1/F3, arrows, Esc, modifiers, scan vs ASCII, Ctrl+] isolation | no leaked `[`/`~`; DOS commands and installer UI |
| IRQ/PIT | PIC IMR/IRR/ISR/EOI, PIT mode2/3, DOS ticks, IF masking | IRQ0 on; stable DOS/keyboard/disk tests |
| 386 real mode | 32-bit ops/prefixes, SIB, FS/GS, REP and faults | all tests in live single CPU state |
| Protected mode | GDT/IDT, CR0, segment checks, IRQ/IRET, privilege, memory | DOS extender smoke host + RP2350 |
| DOS6 install | `SYS`, `COMMAND.COM`, MBR/VBR, CONFIG.SYS, AUTOEXEC.BAT | boot from C and run `VER`, `DIR`, `MEM` |
| Descent | all installation floppies, game startup, VGA, input, sound | graphical title/menu, then gameplay |

## Concrete completion sequence

1. Use clean DOS console now. Preserve the current floppy-first known-good image, and back up C HDD file.
2. Consolidate VGA BIOS function coverage with one host conformance harness, starting from current `12h/BL=10h` EGA query; exercise `INSTALL.EXE` without guest safe-stop.
3. Finish fully installed C: with real nonzero system files and HDD boot; keep separate opt-in A floppy.
4. Restore IRQ0 delivery; run disk/keyboard regressions.
5. Unify 386 CPU / memory model; show >4 MiB RAM only when actually backed; validate real mode + extender transitions.
6. Complete VGA and sound/input demanded by Descent. Measure speed after correctness.

## Limits of this audit

The repository's last public commit predates some of the user's applied installers; this document reports newer successes from the current hardware log but code-level coverage from public files and verified installer outputs. Unsupported subsystems are *implementation targets*, not confirmed failures beyond the specific missing INT10 case. The clean-console tool filters the **host display only**; it does not reduce firmware debug/USB load until runtime log-level gating is implemented.
