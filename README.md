# blitzBUS DOS 6.22 HDD Stage 1

## Why this exists

The 2026-10-14 03:44 test booted genuine MS-DOS 6.22 **Setup** (not an already-installed command prompt), reached its floppy-install path, and handled Enter/Escape keystrokes. Setup reported that no hard disk was available. The existing `DRIVE_C.IMG` is a DOS2 private FAT16 *superfloppy*, not BIOS fixed disk `80h`.

This stage adds a separate BIOS 80h hard disk with an actual MBR + active FAT16 partition, and **never reuses or alters** the DOS2 C: image. It is opt-in through `DOS622.TXT=1` and image presence.

## Contents

- `DOS622_HDD.IMG` -- ready-to-use 33,546,240-byte disk image (65 cylinders, 16 heads, 63 sectors, 512 bytes/sector). Contains active FAT16 partition at LBA 63. The partition is initially empty and NOT yet an installed DOS 6.22 system.
- `bb_make_dos622_hdd_v1.py` -- independently regenerates the image without overwriting existing files (`--selftest`).
- `bb_dos622_hdd_v1.py` -- reversible, anchored installer (`selftest`, `probe`, `apply`, `verify`, `restore`, `recover`). It updates the SHA manifest cascade but leaves historical backups intact.
- `bb_dos622_hdd_sd_v1.inc` -- separate SD file open, validation and synchronized sector reads/writes.
- `bb_dos622_hdd_bios_v1.inc` -- PC/AT BIOS `INT 13h` disk 80h: reset/status, CHS read/write/verify, drive parameters, size, standard failures.
- `bb_hdd_host_test.c` -- independently compiled host test; uses stubbed memory and disk I/O.

## Installation

1. Copy the three source/install files (`bb_dos622_hdd_v1.py`, `bb_dos622_hdd_sd_v1.inc`, `bb_dos622_hdd_bios_v1.inc`) to `C:\blitzBUS`. **Do not copy the `.inc` files into `src` or `sd_boot` manually**; the installer handles placement and reversible backups.
2. Run in PowerShell:

```powershell
cd C:\blitzBUS
python .\bb_dos622_hdd_v1.py selftest
python .\bb_dos622_hdd_v1.py probe
```

3. **Only if `probe` passes:**

```powershell
python .\bb_dos622_hdd_v1.py apply
python .\bb_dos622_hdd_v1.py verify
python .\bb_dos622_atbios_v1.py verify
python .\bb_dos622_vga12_30_v1.py verify
python .\bb_dos622_keyba2_v3.py verify
```

4. Place `DOS622_HDD.IMG` on the microSD card **at** `BLITZBUS/DOS622_HDD.IMG`, alongside `DOS622.IMG`. Keep `BLITZBUS/DOS622.TXT` containing `1`. **Back up the microSD card first.**
5. Keep the same `BB_CPU=286`, `BB_CODE_KB=232`, LCD clock options and IRQ0 diagnostic isolation. Run the original `scripts/bb_live_run.ps1` build/flash/interactive capture.

## Expected log

```
[bb622-hdd] BIOS 80h mounted RW 65x16x63, 65520 sectors, partition LBA 63, FAT16
[bb622-hdd] read LBA=0 OK
[bb622-hdd] read LBA=63 OK
```

The BIOS disk read probes are determined by DOS6 Setup and may not include both example LBAs. The important behavioral change is that Setup discovers a fixed disk and can select it for installation.

## Important caveats

- **This is a test-stage installer, not yet a completed DOS6 HDD boot path.** The bootloader in the image's MBR loads the partition boot sector, but the partition boot sector is unbootable until DOS Setup/SYS installs proper DOS 6.22 system files. Changing the boot selection from floppy to hard disk will be a separate gated step after installation succeeds.
- The setup floppy `DOS622.IMG` remains read-only. Do not attempt to install DOS *to A:*; target the newly exposed hard disk only. No genuine MS-DOS binaries are included.
- The new BIOS HDD is independent of the DOS2 `DRIVE_C.IMG`. Do not rename or delete `DRIVE_C.IMG`.
- BIOS CHS supports `0x00,0x01,0x02,0x03,0x04,0x08,0x09,0x0D,0x15`, with 64 KiB DMA and track-boundary checks. EDD/LBA packet operations `AH=41h/42h` are **not advertised or implemented**.
- Non-boot BIOS services remain incomplete; IRQ0 is still suppressed for DOS6, 386 protected mode is still a separate smoke test, and the ANSI arrow escape input is not yet translated into PC scan codes.
- A DOS6 Setup hard-disk check may find further requirements beyond the BIOS calls implemented. It is safer to diagnose those from hardware than spoof successful unimplemented calls.
- FatFs synchronizes every guest sector write to preserve correctness. **Never remove power while guest Setup writes.**
- SRAM is near capacity; this adds a `FIL` file object. Verify that the Pico firmware still links with adequate stack reserve.
- If `probe` fails, the source layout changed; **do not manually force or alter SHA manifests.**

## Test status

- Image builder/selftest PASS: MBR, FAT16 BPB, identical FATs, partition bounds, refused overwrite.
- Reversible installer synthetic LF/CRLF test PASS, multi-source SHA dependency update + exact rollback.
- C11 host test PASS: `INT 13h` drive 80h geometry, capacity, CHS read, unsupported call, DMA-boundary failure and absent drive behavior.
- Pico compilation / real hardware integration / DOS 6.22 Setup **not yet tested**.
