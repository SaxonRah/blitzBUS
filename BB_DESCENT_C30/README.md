# blitzBUS 30 MiB DOS C: migration — prerequisite for Descent install

Descent's five-floppy edition is listed around 16 MB **installed**, so 16 MiB C: is too small if keeping other files or staging archives. MS-DOS 2.00 block-driver BPB uses a 16-bit total-sector field; **30 MiB (61,440 sectors)** is a conservative ceiling rather than 32 MiB (65,536 sectors, cannot fit).

## Safe sequence

1. Power the Pico **off**. Remove the SD card and connect it to Windows. Backup `O:\BLITZBUS\DRIVE_C.IMG` and `BOOT.IMG`.
2. Extract ZIP under `C:\blitzBUS`.
3. Run on Windows:

```powershell
python .\BB_DESCENT_C30\upgrade_c.py migrate --source O:\BLITZBUS\DRIVE_C.IMG --output C:\blitzBUS\DRIVE_C_30M_NEW.IMG
python .\BB_FAT16_TOOL\fat16tool.py --image C:\blitzBUS\DRIVE_C_30M_NEW.IMG ls
python .\BB_DESCENT_C30\upgrade_c.py firmware --root C:\blitzBUS
```

4. **With Pico off**, archive old SD `DRIVE_C.IMG` somewhere safe, then copy `DRIVE_C_30M_NEW.IMG` to SD as `O:\BLITZBUS\DRIVE_C.IMG` (same exact filename).
5. Eject SD, insert in Pico, use normal `bb_live_run.ps1` to rebuild and flash. Verify `C:`, `DIR`, `TYPE TEST.TXT` and check ~30 MiB free.

`upgrade_c.py firmware` changes only the private C backing file `sd_boot/bb_sd_boot.c` and private DOS driver `sd_boot/bb_msdos2_boot.c`. Backups are placed in `sd_boot/c30_backup`. The original microDOS source and flashing logic remain unchanged. Firmware patch must run *after* the generic DISK patch if that is installed. Rerunning firmware patch will deliberately fail the anchors, preventing accidental double patches.

## Descent install

The existing five disk images are 1.44 MB FAT12. Their `.SOW` files are compressed multi-volume game archives. **Do not copy five raw floppy images into C: and expect the installer to unpack into free space in the same 30 MiB image**: it wastes ~7 MiB and may still be tight. Instead keep disk images on physical SD (`SD:\...`) and mount them into B: using the new `DISK` command.

Test `A>DISK SD:\BLITZBUS\DESCENT1.IMG`, then `B:`, `DIR`; run `B>INSTALL` to try the original installer. When prompted for the next floppy, terminate or suspend the installer only if it is safe, issue `A>DISK SD:\BLITZBUS\DESCENT2.IMG`, and retry; an installer blocking on a disk-change prompt **cannot receive another command at A:**. That requires live-swapping through a hotkey, host console or installer pre-extraction. See note below.

The Descent installer may need DOS 5+ and a 386 CPU / DOS extender. blitzBUS presently boots DOS 2.00 and emulates 8086, so even with enough disk space this might *not* execute. Hardware-compatible installation on a DOS emulator or Windows host and importing installed files via `fat16tool.py` is a reasonable alternative, and still persists fully on C:.

**This release migrates C: only. It does not yet install Descent itself.** Do not replace your backed-up working SD image until the migrated image is validated. The migration algorithm has been tested on a synthetic populated image, but not on your physical media.
