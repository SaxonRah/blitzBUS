# DOS 6.22 / 386 follow-through milestones

**Validated in hardware 2026-10-14:** MS-DOS 6.22 Setup is executing on Pico Plus 2 RP2350, with BIOS floppy, SD-backed HDD `80h` 65/16/63 CHS, and synchronous sector 0 / 63 writes. Text screen transitions currently exhibit ghosted content from a `scroll_text(n=0)` VGA BIOS bug, addressed by this package pending test. 286 real mode is active, IRQ0 is suppressed. 386/GDT 10/10 is a separate probe.

## Acceptance gates

| Gate | Required behavior | Current assessment |
|---|---|---|
| BIOS VGA text clears | AH=06/07 AL=00 wipes full window, including attributes; physical LCD refreshes | Screen Clear V1 host-tested, not yet on Pico |
| HDD install | MS-DOS Setup can complete on `DOS622_HDD.IMG` without corrupting other images | Disk visible and writes proven; installer not completed |
| Boot installed DOS | MBR active partition, partition VBR, genuine DOS system files, prompt and `VER/DIR` | Not implemented / verified |
| Keyboard | Enter, Escape, Backspace, arrows, F1/F3/F5/F7 as BIOS scans | Enter verified; extended input incomplete |
| Timer/interrupts | PIT ticks and IRQ0 through genuine INT08/1C, PIC EOI | IRQ0 deliberately suppressed |
| 386 memory | A20 and >1MiB backing, truthful INT15 88/E8 and XMS | 1088KiB guest; no advertised extended RAM |
| 386 protected mode | CR0.PE, GDT/LDT, descriptor cache, IDT, exceptions and real-mode return | Only isolated pre-boot 10/10 probe |
| DOS extenders / Descent | Extended-memory allocation, DPMI/VCPI or DOS/4GW requirements tested | Blocked on 386 and RAM |

Keep each gate reversible and measure on-device, preserve parent SHA lineage, never turn on unsupported features to trick DOS Setup. Firmware RAM is approximately 98% reserved: new buffers belong in flash or PSRAM with explicit budgeting.
