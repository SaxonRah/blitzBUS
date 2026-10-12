# blitzBUS clean C: builder

Creates a **new**, clean 30 MiB FAT16 image, retaining only the 512-byte boot sector/BPB from the installed 30 MiB image. No old FAT allocation tables or cluster data are copied. Adds `COMMAND.COM`, generic 175-byte `DISK.COM`, `GAMES/DESCENT` (25 original extracted files), and `TOOLS` (optionally HELLO.TXT).

## Preparation

**Power off Pico and insert SD card into Windows.** Make backups of `O:\BLITZBUS\DRIVE_C.IMG` and `BOOT.IMG`. Do not run while Pico has SD card mounted.

The script extracts `COMMAND.COM` directly from the minimal `O:\BLITZBUS\BOOT.IMG` (360 KiB FAT12). Use the 175-byte `BB_GENERIC_DISK_V1\DISK.COM`. No DOS-side copy is required.

```powershell
cd C:\blitzBUS
Expand-Archive .\BB_C30_CLEAN_BUILD.zip . -Force
python .\BB_C30_CLEAN_BUILD\build_clean_c.py `
  --boot-template O:\BLITZBUS\DRIVE_C.IMG `
  --descent C:\blitzBUS\descent_complete `
  --disk-com C:\blitzBUS\BB_GENERIC_DISK_V1\DISK.COM `
  --boot-a O:\BLITZBUS\BOOT.IMG `
  --output C:\blitzBUS\DRIVE_C_CLEAN.IMG
```

The script validates the archive's key file sizes, imports 25 Descent files, compares SHA-256 for every readback, audits the image for broken chains, crosslinks, orphans, and invalid FAT entries. It refuses to overwrite an existing output.

### Windows verification

```powershell
python .\BB_FAT16_CHAIN_CHECK\check_chains.py C:\blitzBUS\DRIVE_C_CLEAN.IMG
python .\BB_FAT16_TOOL\fat16tool.py --image C:\blitzBUS\DRIVE_C_CLEAN.IMG ls GAMES/DESCENT
```

### Deploy only after verification

```powershell
Copy-Item O:\BLITZBUS\DRIVE_C.IMG C:\blitzBUS\DRIVE_C_BEFORE_CLEAN.IMG
Copy-Item C:\blitzBUS\DRIVE_C_CLEAN.IMG O:\BLITZBUS\DRIVE_C.IMG -Force
```

Safely eject, boot Pico, test `C:`, `DIR`, `CD \GAMES\DESCENT`, `DIR`, and compare file sizes. Test `COPY A:\COMMAND.COM C:\CMDCOPY.COM` and verify persistence only after directory reads succeed.

This does **not** fix any DOS 2.00 free-space accounting bugs, Descent binding, or 386-mode execution. Source DOOM/Descent archive floppies remain untouched.
