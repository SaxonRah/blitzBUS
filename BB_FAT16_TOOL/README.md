# blitzBUS FAT16 image tool — Stage 2E

A standalone Python 3.9+ command-line manager for the **16 MiB FAT16 superfloppy** `DRIVE_C.IMG`. Standard library only. **No firmware changes** and no patches.

## Critical rules

- **Power off / stop the Pico and remove the SD card before editing `DRIVE_C.IMG` on Windows.** The Pico's already-open FatFs file handle and in-memory read cache will not notice host edits. Do not use this utility while the Pico is running, even for a quick test. Safely eject the card from Windows before returning it to the Pico.
- Keep a backup of a working image, especially before first use.
- Mutating operations create an image-sized temporary file **alongside the image**, then atomically replace the image file on successful completion. This requires approximately 16 MiB of *additional free space* on the SD card. A temp file may temporarily remain after abrupt power loss.
- This is a raw FAT16 image tool, not a general Windows drive mounter. It handles standard short 8.3 names, files, and directories, but does not create long-file-name entries.
- The tool does not lock the SD volume or detect a Pico that's actively using it. Obey the rule above.

## Example commands (PowerShell)

```powershell
cd C:\blitzBUS
Expand-Archive .\BB_FAT16_TOOL.zip . -Force

# Backup while Pico is stopped and SD inserted in PC
Copy-Item O:\BLITZBUS\DRIVE_C.IMG C:\blitzBUS\DRIVE_C_BACKUP.IMG

# Examine image
python .\BB_FAT16_TOOL\fat16tool.py info
python .\BB_FAT16_TOOL\fat16tool.py ls

# Create TOOLS directory and import a DOS program
python .\BB_FAT16_TOOL\fat16tool.py mkdir TOOLS
python .\BB_FAT16_TOOL\fat16tool.py import C:\DOS\EDIT.COM TOOLS/EDIT.COM
python .\BB_FAT16_TOOL\fat16tool.py ls TOOLS

# Export a DOS file back to Windows
python .\BB_FAT16_TOOL\fat16tool.py export TEST.TXT C:\blitzBUS\TEST_FROM_DOS.TXT

# Replace an existing DOS file explicitly
python .\BB_FAT16_TOOL\fat16tool.py import C:\DOS\EDIT.COM TOOLS/EDIT.COM --replace

# Delete file; remove empty directory
python .\BB_FAT16_TOOL\fat16tool.py rm TOOLS/EDIT.COM
python .\BB_FAT16_TOOL\fat16tool.py rm TOOLS
```

Pass `--image C:\path\to\DRIVE_C.IMG` **before** the subcommand to choose a different image. Default: `O:/BLITZBUS/DRIVE_C.IMG`.

When finished, eject the SD in Windows, insert into the Pico, boot and verify `C:` in DOS. If an imported program does not run, that is a separate DOS/CPU compatibility issue.

## Supported commands

- `info`: boot-sector geometry and cluster count
- `ls [DOS_PATH]`: list root or directory, with free-space count
- `import HOST_FILE DOS_PATH [--replace]`: copy a host file into image
- `export DOS_PATH HOST_FILE`: copy a DOS file out of image (refuses host overwrite)
- `mkdir DOS_PATH`: create directory, including `.`/`..` records
- `rm DOS_PATH`: delete file or **empty** directory

Limitations: FAT16 only; no recursive directory import/export, renaming, DOS timestamps, image creation, or LFN support. FAT16 cluster chain is checked for cycles; invalid geometries and unsupported FAT variants are rejected. The tool is intended for this project's known image, not recovery of damaged FAT volumes.
