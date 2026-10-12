# blitzBUS — Descent offline installation

This tool uses your **own** `descent_disk1.img` through `descent_disk5.img`. It reads the FAT12 floppy images, assembles the five `DESCENT#.SOW` ARJ segments, extracts them on Windows, and imports the resulting DOS 8.3 files into `C:\GAMES\DESCENT` inside the 30 MiB persistent FAT16 image. It does not modify firmware, `BOOT.IMG`, or floppy images.

**Prerequisites:** `BB_FAT16_TOOL` and `BB_DESCENT_IMPORT` folders next to this folder, plus 7-Zip (`7z.exe`) or ARJ (`arj.exe`). The tool tries both a concatenated ARJ stream and conventional ARJ volume naming, but an uncommon SOW layout might require another extractor. Extraction must succeed completely before import is attempted.

**With Pico OFF, SD card in Windows, and the 30 MiB C: image backed up**, run:

```powershell
cd C:\blitzBUS
Expand-Archive .\BB_DESCENT_OFFLINE_INSTALL.zip . -Force
Copy-Item O:\BLITZBUS\DRIVE_C.IMG C:\blitzBUS\DRIVE_C_BEFORE_INSTALL.IMG

# Extract only, DO NOT change C: yet
python .\BB_DESCENT_OFFLINE_INSTALL\install_descent.py --extract-only

# Inspect extracted files
Get-ChildItem .\descent_extracted -Recurse | Select-Object FullName,Length

# Dry run: check 8.3 DOS paths and free space
python .\BB_DESCENT_OFFLINE_INSTALL\install_descent.py --install-only --dry-run

# Atomically import into persistent C:\GAMES\DESCENT
python .\BB_DESCENT_OFFLINE_INSTALL\install_descent.py --install-only

python .\BB_FAT16_TOOL\fat16tool.py ls GAMES/DESCENT
```

If 7-Zip is not found, add `--extractor 'C:\Program Files\7-Zip\7z.exe'` to the extraction command. Use a **new empty** `descent_extracted` folder; the script refuses to overwrite staged data. `--image` overrides the C: image path, default `O:\BLITZBUS\DRIVE_C.IMG`.

The import is transactional at the image-file level (temporary same-folder image followed by replacement); you should also keep the independent pre-install backup. Do not run with Pico powered on or the image otherwise mounted. The importer refuses to overwrite an existing `GAMES/DESCENT` directory and validates every imported file byte-for-byte before commit. The existing `C:\DESCENT\DISK1..DISK5` folders are left alone.

**Important:** Installing files does **not** make Descent run under current MS-DOS 2.00/8086 execution. Descent needs 386 protected-mode support, more recent DOS services, VGA, and memory management; those are future CPU/runtime milestones. 

**About NEWTEST.TXT:** Windows and DOS reporting the same incorrect 21 bytes means the file's stored bytes are incorrect, not a character-echo problem. The precise original corruption point is not yet proven. Preserve the old 16 MiB backup to compare that file if needed. This importer doesn't touch `NEWTEST.TXT`.
