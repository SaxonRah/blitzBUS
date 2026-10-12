# blitzBUS generic DOS `DISK` V1 (experimental)

Implements the DOS command `DISK SD:\folder\disk.img` or `DISK C:\folder\disk.img`. A `C:` path addresses an ordinary 8.3-named file within `DRIVE_C.IMG`; an `SD:` path addresses a file on the SD card's FAT filesystem. The selected image appears on DOS `B:`. The original DOS `A:` remains the boot floppy and `C:` remains persistent. The selected `B:` image is **read-only** and must be a **1,474,560-byte (1.44 MB) floppy image**; generic 360 KiB, 720 KiB and 1.2 MB images require future per-image BPB support. DOS filenames and directory names within C: paths must use 8.3 syntax.

This firmware has **not** been Pico-cross-compiled or hardware-tested. **Back up BOOT.IMG and DRIVE_C.IMG before use.** Do not overwrite the boot image until the new `DISK.COM` and firmware work on your actual hardware.

## Preparation and installation

Prerequisite: **the previous BB_DESCENT_LIVESWAP firmware source files must already be installed** (`sd_boot/bb_sd_boot.c`, `sd_boot/bb_msdos2_boot.c`). The installer stops if the expected source version is absent; it does not overwrite files on a failed version check. Use the full installer from that bundle if necessary.

```powershell
cd C:\blitzBUS
Expand-Archive .\BB_GENERIC_DISK_V1.zip . -Force
python .\BB_GENERIC_DISK_V1\install.py --root C:\blitzBUS
```

For a first test, **leave your current BOOT.IMG alone** and import `DISK.COM` to the current `C:` image using the FAT16 tool while the Pico is off:

```powershell
python .\BB_FAT16_TOOL\fat16tool.py import .\BB_GENERIC_DISK_V1\DISK.COM DISK.COM
```

After rebuilding/flashing, DOS can run `C:\DISK.COM SD:\BLITZBUS\DESCENT1.IMG` (or from C: prompt `DISK SD:\BLITZBUS\DESCENT1.IMG`). To put the command directly in A: without a DOS copy step, build a **separate minimal image** (the tool copies COMMAND.COM from the existing BOOT.IMG):

```powershell
python .\BB_GENERIC_DISK_V1\make_minimal_a.py --source O:\BLITZBUS\BOOT.IMG --disk-com .\BB_GENERIC_DISK_V1\DISK.COM --output C:\blitzBUS\BOOT_MINIMAL_TEST.IMG
```

Keep both original and generated images. After the generic command is verified from C:, power off Pico and replace `BOOT.IMG` with the minimal image, retaining the original off the SD card for rollback. Make sure the SD card is safely ejected from Windows before power-on.

Example DOS commands once the minimal A: is in place:

```text
A>DIR
COMMAND  COM
DISK     COM
A>DISK SD:\BLITZBUS\DESCENT1.IMG
A>B:
B>DIR
B>A:
A>DISK C:\GAMES\DESCENT\DISK2.IMG
A>B:
B>DIR
```

The SD card's host `SD:\...` names are FAT filesystem paths starting at its root; there is no additional `BLITZBUS` implicit prefix. If you copied the floppy images under `O:\BLITZBUS`, use `SD:\BLITZBUS\DESCENT1.IMG`.

FAT16-in-FAT32 nested mounting traverses cluster chains as B: sectors are read, including fragmented files. The first version is optimized for correctness rather than random read speed and adds no large static sector map.

Rollback private source files (then rebuild firmware):

```powershell
python .\BB_GENERIC_DISK_V1\install.py --root C:\blitzBUS --restore
```
