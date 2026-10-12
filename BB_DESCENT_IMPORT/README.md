# blitzBUS Descent DOS floppy importer

This tool copies **the files inside** `descent_disk1.img` through `descent_disk5.img` to the existing `DRIVE_C.IMG` as five folders. It does **not** simply store the floppy images as opaque files.

Target layout:

```
C:\DESCENT\DISK1\...
C:\DESCENT\DISK2\...
C:\DESCENT\DISK3\...
C:\DESCENT\DISK4\...
C:\DESCENT\DISK5\...
```

Run on Windows PowerShell from `C:\blitzBUS` after extraction:

```powershell
python .\BB_DESCENT_IMPORT\import_descent.py --dry-run
```

Check the detected floppy formats and filenames. With the Pico powered off, the SD card connected to Windows and a copy of `O:\BLITZBUS\DRIVE_C.IMG` safely backed up, run:

```powershell
Copy-Item O:\BLITZBUS\DRIVE_C.IMG C:\blitzBUS\DRIVE_C_BEFORE_DESCENT.IMG
python .\BB_DESCENT_IMPORT\import_descent.py
python .\BB_FAT16_TOOL\fat16tool.py ls DESCENT
python .\BB_FAT16_TOOL\fat16tool.py ls DESCENT/DISK1
```

Safely eject the SD card, reinsert in Pico and boot. In DOS:

```dos
C:
DIR \DESCENT
DIR \DESCENT\DISK1
```

### Important limitations

* **This stages the original install disks; it does not install Descent.** Multi-disk installers may ask to swap floppy A:, and copying disk contents to C: directories does not provide disk-swap emulation. We can examine the directory listings for a suitable install procedure.
* Running Descent is a separate compatibility issue (486/Pentium-class requirements, DOS extenders, VGA, memory, and game size). The 16 MiB C: image may be too small for a full installation.
* Only standard raw DOS FAT12/FAT16 floppy images are supported. Unsupported or compressed formats fail without modifying `DRIVE_C.IMG`.
* DOS 8.3 filenames and directories are preserved. Nothing is deleted or overwritten inside the existing FAT16 image; if `DESCENT` already exists, the operation refuses to run.
* All destination changes are made **once**, via atomic replacement after extraction and FAT16 allocation succeed. The source images are never modified.
* Never edit `DRIVE_C.IMG` from Windows while the Pico has it mounted.
