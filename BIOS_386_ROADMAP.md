# blitzBUS full DOS 6.22 + 386 PC/AT compatibility roadmap

**Based on actual 2026-10-14 DOS622.IMG hardware traces and the public blitzBUS modules** (not a certification of full compatibility).

## Baseline verified in captures

- RP2350 Pico Plus 2, `clk_sys=300 MHz`, 8 MiB PSRAM, guest allocation 1,088 KiB, DOS conventional 640 KiB.
- SD A: `DOS622.IMG` boot sector and real `IO.SYS`/MS-DOS startup; C: 32MB image opened, separate DOS2 infrastructure.
- Native 80286 real-mode blitz86 uses 232 KiB code cache; DOS boots far enough to install COMMAND/KEYB hooks.
- KEYB BIOS `INT16/AH92` and `A2` probes handled; refresh bit at 61h emulated; VGA alternative cursor and 400-line selector handled.
- The new observed stop is `INT10 AX1114` at `2600:017B`.
- `bb_386_pico_probe.inc` tests 32-bit arithmetic, SIB addressing, FS override, 32-bit call/return and GDT lookup on a **private** B86Cpu; it restores the HMA and does not switch the actual DOS guest into 386 mode.

## Milestone A: DOS 6.22 text-mode clean boot

Implement and regression-test the **actual semantics** of missing text BIOS: font geometry (`1104/1114`), font information (`1130` only after real guest font bytes exist), string write (`AH13`), additional VGA alternate services as observed, keyboard queue, BDA/IVT consistency, disk geometry and floppy change line.

**Pass condition:** DOS622.IMG reaches `A:\>` with `DIR`, `VER`, `MEM`, `TYPE`, `COPY` behaving correctly; keyboard accepts repeated input after boot and Ctrl+] still reports native statistics. Avoid claiming `AX1130` until ROM font pointers refer to actual readable guest bytes.

## Milestone B: PC/AT timer, PIC, PIT and keyboard controller

- Restore IRQ0 through master/slave 8259 PIC, including ICW/OCW, masks, in-service, end-of-interrupt and correct IF-sensitive delivery.
- Proper PIT channel 0 scheduling and channel 2 speaker output; port 61h bit 4 refresh and bit 5 PIT2 output should agree with the PIT model.
- INT08/INT1C BDA tick and midnight flag, INT1A time services, IRQ1/INT09 keyboard scan handling, 8042 status/data commands on ports 60h/64h.
- Remove IRQ0 isolation only after a before/after test shows stable keyboard input and timer tick progression.

**Pass condition:** DOS timer advances at expected rate; keyboard remains interactive; INT1C fires; no repeated spurious interrupts, no vector-0 crashes.

## Milestone C: BIOS disks, media and persistence

- Complete INT13 geometry/error semantics for A:, B: and a bootable fixed disk 80h, including carry/status, retry/reset/media change, buffer crossing checks, sector reads and writes (writes only on explicitly writable media).
- Make a 6.22-bootable FAT16 C: if desired, with validated MBR/partition BPB layout; avoid treating DOS2's C: superfloppy as an IBM PC BIOS hard disk.
- Verify DOS `SYS`, `FORMAT`, `CHKDSK` and filesystem operations against disposable image copies before enabling any new writable BIOS path.

**Pass condition:** DOS 6.22 boots its own COMMAND.COM and can read/write a writable drive image without corruption.

## Milestone D: real 386 memory and BIOS

- Select 80386 for the **live guest**, not just the isolated `bb_386_pico_probe` test; preserve 16-bit real-mode performance and prove 32-bit prefix behavior, 32-bit stack, segment overrides, exception delivery.
- Build a coherent A20 gate model (port 92h, 8042, INT15 AX2400-2403), including real 1 MiB wrap with A20 disabled, HMA when enabled, and generated guest-code coherence.
- Allocate actual backed RAM beyond 1 MiB before advertising it. INT15/AH88, AXE801 and E820 must agree with the same physical memory map and guest size. Do not advertise PSRAM reserved for JIT, shadow/metadata, LCD or stacks.
- XMS v3 support via HIMEM.SYS-compatible XMS multiplex interface (`INT2F AX4300/4310`), HMA ownership, move locks and A20 reference counting. EMS (`INT67`) is separate if desired.
- Full descriptor and protected-mode machinery: GDTR/IDTR, LDTR/TR, selector privilege, CR0.PE transitions, 16/32-bit gates, exceptions and IRET, paging/CR3 only if actually supported.
- BIOS services such as INT15 AH87 block move must honor physical memory mappings, descriptors and bounds instead of copying arbitrary guest bytes.

**Pass condition:** DOS reports the installed XMS RAM, a 386 DOS extender enters and exits protected mode, can access extended RAM without corrupting conventional DOS, and all 286/DOS2 tests remain green.

## Milestone E: application compatibility

- DOS 6.22 `MEM`, `EDIT`, `QBASIC`, `CHKDSK` tests; optional HIMEM, EMM386 only after V86 mode and paging/interrupt virtualization are real.
- Test 386 DOS extenders (`DPMI`, VCPI where supported), then `3DBENCH` as a 32-bit instruction throughput regression, then Descent's actual CPU/memory/video/audio requirements.
- Avoid promising Descent's speed based on raw 3DBENCH scores: XMS, DOS extender, VGA and sound compatibility are independent gates.

## Test discipline

Use one `selftest -> probe -> apply -> verify -> hardware capture` cycle per coherent subsystem; source-hash guard and parent-manifest integrity checks must be mandatory. Keep a golden DOS2 test and a known-good boot log. Changes that fake hardware support must be rejected, even when they advance boot farther in the short term.

## Known outstanding blockers (not solved by Phase 1)

- Full ROM fonts/INT10 font-pointer semantics
- 8259/PIT/IRQ0 behavior and IRQ1/8042
- INT13 hard disk boot/write handling
- Live 80386 protected-mode execution, exceptions/privilege, system instructions
- Backed extended RAM + accurate INT15 memory map + A20/XMS
- DPMI/VCPI/V86 and sound hardware
