# blitzBUS Stage 2F: virtual floppy B: (read-only)

Adds a real 1.44 MiB FAT12 DOS B: drive independent of persistent A: and C:. Reads sector data directly from the original Descent images on the microSD card.

**Important limitations**: This first version is read-only, chooses the disk at firmware boot, and requires a Pico power-off/reboot to change disks. It does **not** implement live floppy change notifications, fake disk-change lines, or DOS installer drive-change prompting. It is a stepping stone, not a guarantee Descent INSTALL.EXE will work.

Back up `BOOT.IMG`, `DRIVE_C.IMG`, and your current firmware. Power OFF Pico and insert the SD card into your Windows PC. Do not access or modify the SD card from Windows while the Pico has mounted it.

## 1. Put all original floppy images on SD

```powershell
cd C:\blitzBUS
python .\BB_DESCENT_VFLOPPY_B\prepare_disks.py --source C:\blitzBUS\games --sd O:\BLITZBUS --select 1
```

This copies (does not delete or modify originals) `descent_disk1.img` to `O:\BLITZBUS\DESCENT1.IMG`, and so on up to `DESCENT5.IMG`. `O:\BLITZBUS\B_DISK.TXT` holds a single ASCII digit (`1`–`5`). Disk 1 is the default.

If you previously imported the files into `C:\DESCENT\DISK1` through `DISK5`, those are unrelated and can remain. Disk images stored in host FAT32 do not consume space inside the 16 MiB DOS C: image.

## 2. Install private firmware source replacements

```powershell
python .\BB_DESCENT_VFLOPPY_B\install.py --root C:\blitzBUS
```

The installer backs up the *two* private source files to `C:\blitzBUS\sd_boot\stage2e_b_floppy_backup`, validates exact anchors, then writes the complete modified files. It does not change the original microDOS repo source, Windows console script, clock settings, or flash script.

## 3. Build and flash using your unchanged workflow

```powershell
$env:BB_SD_BOOT = '1'
$env:BB_LCD_PERI_HZ = '150000000'
$env:BB_LCD_SPI_HZ = '75000000'
$env:BB_LCD_LACE = '1'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180
```

Look for `[bb-sd-b] B: DESCENT1.IMG READ-ONLY 1440 KiB mounted` and then use DOS:

```dos
B:
DIR
```

Use `DIR B:` and optionally `COPY B:\INSTALL.EXE C:\INSTALL.EXE` if you want to verify file transfer. Then check `A:`, `C:`, `DIR`, and a 3DBENCH regression.

## 4. Switch to disk 2, 3, 4, or 5 (reboot required)

Power off Pico, move SD card to Windows, and run:

```powershell
python .\BB_DESCENT_VFLOPPY_B\prepare_disks.py --selection-only --sd O:\BLITZBUS --select 2
```

Safely eject, reinsert, boot Pico. `B:\DESCENT2.SOW` should be visible.

## 5. Roll back

```powershell
python .\BB_DESCENT_VFLOPPY_B\install.py --root C:\blitzBUS --restore
```

Then rebuild. This reverts B: to Stage 2D alias behavior but does not change image files on the SD card.

## Safety and future plans

B: is read-only to prevent the original game floppy files from being modified. Stage 2F supports boot-time selection only; for real installer swapping at prompts, we will need runtime selection plus DOS media-change handling. FAT16 C: write-through remains synchronous, and the clean C: read cache remains intact.

**Validation**: Installer Python syntax and local source-anchor checks only; user Pico compilation and DOS behavior remain untested.
