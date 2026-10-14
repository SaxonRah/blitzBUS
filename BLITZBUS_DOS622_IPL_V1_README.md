# blitzBUS — MS-DOS 6.22 real-floppy boot, IPL v1

This is the **first experimental, opt-in real DOS boot path**. It does NOT rename or emulate the DOS 2 kernel as 6.22. The device executes the real boot sector from a user-provided MS-DOS 6.22 floppy image and provides initial BIOS interrupts needed by that loader.

## Scope and limitations

- The existing, successful MS-DOS 2.00 `BOOT.IMG` + DOS2 kernel path remains the default unless `/BLITZBUS/DOS622.TXT` starts with `1`.
- New `/BLITZBUS/DOS622.IMG` must be a *bootable 1,474,560-byte FAT12 1.44 MB floppy image* containing `IO.SYS`, `MSDOS.SYS`, and `COMMAND.COM`. Provide your own legitimately obtained MS-DOS files. No Microsoft code is distributed here.
- The alternate image is mounted **read-only** so exploratory boots cannot corrupt it. BIOS writes return a write-protection error.
- BIOS services implemented initially: `INT 13h` A: diskette CHS reset/status/read/verify/geometry/type; `INT 11h` equipment; `INT 12h` conventional memory; `INT 15h/AH=88h` reports no extended memory; `INT 1Ah/AH=00h,01h` BDA tick access. Existing graphics (`INT 10h`) and keyboard (`INT 16h`) adapters remain active.
- First target is witnessing real DOS 6.22 boot-sector execution and read requests. **This does not yet guarantee the DOS 6.22 command prompt boots.** We will fill BIOS compatibility gaps from traces.
- The existing `DRIVE_C.IMG` is a FAT16 superfloppy without a hard-disk partition table. This initial BIOS does not announce it as DL=80h. We will build an MBR/partition-compatible C: path later. DOS 6.22 shell must first boot from A:.
- `BB_CPU=286` continues to use the existing working fast interpreter/JIT and 232 KiB code cache. New BIOS and image-mount routines live in flash; image scratch memory is in PSRAM.

## Install full files (no Git patch)

1. Extract all ZIP files into `C:\blitzBUS`. In particular, leave `bb_dos622_sd.inc` and `bb_dos622_bios.inc` at that root initially. The installer copies their full contents into the target source folders.
2. Run:

```powershell
cd C:\blitzBUS
python .\bb_dos622_ipl_v1.py selftest
python .\bb_dos622_ipl_v1.py probe
python .\bb_dos622_ipl_v1.py apply
python .\bb_dos622_ipl_v1.py verify
```

The installer changes exactly two existing source files, `C:\blitzBUS\sd_boot\bb_sd_boot.c` and `C:\blitzBUS\src\bb_live.c`, while creating `sd_boot\bb_dos622_sd.inc` and `src\bb_dos622_bios.inc`. It refuses duplicate applications and stores original file bytes with SHA-256 hashes.

To restore the pre-IPL source exactly, run `python .\bb_dos622_ipl_v1.py restore`. If you subsequently modify the installed files, verify and restore intentionally fail instead of overwriting later work.

## Prepare an authentic bootable MS-DOS 6.22 floppy

A DOS 6.22 *installation disk* is not automatically guaranteed to be a bootable *system disk*, so use a verified bootable image prepared by MS-DOS `FORMAT /S` or `SYS`, or a known-good system floppy image from media you own. It must have its actual boot sector and system files (do not simply drag and drop files onto a blank FAT floppy image).

The included Windows Python image tool audits the BPB, boot-sector signature, root filenames, and image size, then stages it onto your SD card. These structural checks cannot authenticate the DOS version or fully prove bootability:

```powershell
cd C:\blitzBUS
python .\bb_dos622_image.py "C:\DOS622\boot622.img"
python .\bb_dos622_image.py "C:\DOS622\boot622.img" --sd-dir "G:\BLITZBUS"
```

Substitute the actual source image path and actual SD drive letter. The staging tool creates `/BLITZBUS/DOS622.IMG` and `/BLITZBUS/DOS622.TXT` (containing `1`). It will not overwrite an existing DOS622.IMG unless `--replace` is supplied. Keep your original image archived because the guest is experimental.

To disable MS-DOS 6.22 boot, change `G:\BLITZBUS\DOS622.TXT` to a single `0` (or delete the selector). **No source rollback or recompilation is required to revert to DOS 2.**

## Build and capture

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
  -MicroDOS C:\microDOS `
  -Blitz86 C:\blitz86_v2 `
  -Port COM5 `
  -Seconds 180
```

Expect new indicators:

```text
[bb-dos622] DOS622.IMG boot candidate mounted A: 1440KiB READ-ONLY (opt-in)
[bb-dos622] ENTER real boot sector 0000:7C00, BIOS DL=00; image read-only
[bb-dos622] read lba=... OK
```

If the DOS 6.22 boot attempt fails, provide the console capture, especially messages following the `ENTER` line. A generic BIOS call may fall through to the original 8086 IVT. We need to trace and implement those services individually. The actual RP2350 link and boot are **not yet verified** for this change.

## Why this architecture

The present microDOS bootstrap requires a specific 16,690-byte MS-DOS 2.00 `MSDOS.SYS` and starts directly at the kernel's private SYSINIT call contract, which is not compatible with MS-DOS 6.22. The new path keeps that system for fallback but takes the real PC boot route: `boot sector → IO.SYS → MSDOS.SYS → COMMAND.COM`. MS-DOS boot-sector code depends on BIOS INT 13h to fetch `IO.SYS`; it cannot use the existing DOS 2 device-driver request packet interface.

## Suggested next steps

Once the boot trace shows progress through the loader, complete the PC BIOS services that actual IO.SYS requires. Then add DOS6's hard-disk BIOS path (an MBR-wrapped FAT16 partition), DOS 6.22 file write support behind an explicit testing option, and larger guest memory for DOS extenders such as Descent. Only when the guest announces the real MS-DOS 6.22 version and COMMAND.COM boots should we call the stage complete.
