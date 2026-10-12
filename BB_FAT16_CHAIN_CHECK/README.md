# FAT16 full chain audit for blitzBUS

With the Pico powered off, extract into C:\blitzBUS and run:

```powershell
python .\BB_FAT16_CHAIN_CHECK\check_chains.py C:\blitzBUS\DRIVE_C_TEST_REPAIRED.IMG --json C:\blitzBUS\FAT_CHAIN_REPORT.json
```

This checker is read-only. It traverses the root and subdirectories, follows full FAT16 chains, verifies that regular files have exactly the expected number of clusters, finds duplicate cluster ownership, and enumerates orphaned clusters and invalid FAT links. It does not modify, repair, or mount the image. Compare against the pre-repair image if helpful.
