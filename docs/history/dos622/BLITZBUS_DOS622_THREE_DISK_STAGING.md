# blitzBUS — Stage all three MS-DOS 6.22 floppy images

The supplied image names are:

```text
C:\dos622\dos-622-disk1.img
C:\dos622\dos-622-disk2.img
C:\dos622\dos-622-disk3.img
```

The included `bb_dos622_stage3_v1.py` is a self-contained Windows-friendly staging tool. It does **not** include MS-DOS, modify disk image contents, or require a new firmware build. It expects the experimental `bb_dos622_ipl_v1` boot layer to be installed separately. The boot layer currently mounts only Disk 1 and does **not** support runtime disk swapping. Disks 2/3 are staged in preparation for later work.

## 1. Extract and run selftest

Unzip `bb_dos622_stage3_v1_bundle.zip` into `C:\blitzBUS` and use PowerShell:

```powershell
cd C:\blitzBUS
python .\bb_dos622_stage3_v1.py --selftest
```

## 2. Validate the *actual* three images on C:\dos622

```powershell
python .\bb_dos622_stage3_v1.py --source-dir "C:\dos622"
```

Expect FAT12 geometry, OEM fields, root-file counts, and SHA-256 hashes for each disk. Disk 1 must contain nonempty root entries for `IO.SYS`, `MSDOS.SYS`, and `COMMAND.COM`. Passing structural checks doesn't authenticate the version or guarantee the boot path will complete.

## 3. Copy onto the SD card

The SD card is `G:` in this example; substitute its real Windows letter. Ensure `G:\BLITZBUS` exists and contains the existing `BOOT.IMG`.

```powershell
python .\bb_dos622_stage3_v1.py `
  --source-dir "C:\dos622" `
  --sd-dir "G:\BLITZBUS"
```

This copies:

```text
DOS622.IMG       <- dos-622-disk1.img  [active boot]
DOS622D2.IMG     <- dos-622-disk2.img  [not yet mounted]
DOS622D3.IMG     <- dos-622-disk3.img  [not yet mounted]
DOS622.TXT       <- 1\n              [opt into experimental DOS 6.22 boot]
```

Existing DOS 2 `BOOT.IMG` and `DRIVE_C.IMG` are untouched. If the target already contains an image with different bytes, the utility refuses to overwrite it unless you deliberately add `--replace`. It copies to temporary files, checks SHA-256, then atomically renames each. Only after all three are staged does it enable the selector.

## 4. Boot the Pico and gather the first DOS 6.22 trace

```powershell
cd C:\blitzBUS
python .\bb_dos622_ipl_v1.py verify

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

Look for the `[bb-dos622]` lines, especially `ENTER real boot sector` and `read lba=...`. If booting fails, capture the entire log so we can fix the next missing BIOS service. Booting a DOS 6.22 installer disk will not by itself create a bootable hard disk. `DRIVE_C.IMG` is currently a FAT16 superfloppy with no MBR, and the DOS 6.22 hard-drive BIOS service path is a separate milestone.

## Revert to the existing MS-DOS 2 boot

Without changing firmware:

```powershell
Set-Content -Path 'G:\BLITZBUS\DOS622.TXT' -Value '0' -NoNewline -Encoding ascii
```

Eject the SD card cleanly, restart the Pico, and the original DOS 2 boot remains the default. Keep the archival 62.5 UF2 and corresponding source snapshot untouched.
