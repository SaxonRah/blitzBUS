# blitzBUS generic DISK command — Stage 1 (minimal A: builder)

This package completes only the safe boot-image reduction. It DOES NOT implement generic `DISK C:\...` or `DISK SD:\...` mounting. Do not mistake the old numeric-only DISK.COM for the future pathname-enabled DISK.COM.

## Intended contract

- `A:` = 360 KiB FAT12 boot/tools image holding `COMMAND.COM` and `DISK.COM` only. MS-DOS kernel remains embedded in firmware as before.
- `B:` = swappable read-only FAT12/FAT16 floppy-image drive.
- `C:` = unchanged persistent FAT16 hard-disk image.
- `DISK C:\FOLDER\DISK.IMG`: resolve a DOS FAT16 8.3 path **inside C: image**, map file's FAT cluster chain and sector offsets to B:, even when fragmented.
- `DISK SD:\FOLDER\DISK.IMG`: open native FAT32/FatFs card path read-only and map its sectors to B:.
- Support quoted filenames containing spaces on SD and DOS path normalization; do not silently rename the user's file.
- Reject non-512-byte-sector images or unsupported geometry, avoid partial switches, and return a clear DOS error code.
- On successful switch, signal DOS's media-changed status and force it to invalidate/remount B: before next access. Avoid swapping if a DOS file handle on B: is still open.
- Do not permit simultaneous Windows and Pico writes to DRIVE_C.IMG. B: images default to read-only.
- C: image backing and any B: inside C: share the same FIL object; preserve the existing C: read cache and invalidate if C: writes modify backing sectors.

## Safe A: reduction (available now)

1. Power the Pico off, remove the card, and back up `BOOT.IMG`.
2. Produce a new image WITHOUT overwriting BOOT.IMG:

```powershell
python .\BB_GENERIC_DISK_STAGE1\make_minimal_a.py `
    --source O:\BLITZBUS\BOOT.IMG `
    --disk-com .\BB_DESCENT_LIVESWAP\DISK.COM `
    --output C:\blitzBUS\BOOT_MINIMAL_TEST.IMG
```

The input `DISK.COM` here is the OLD, numeric-only executable from the previous package; it **does not yet support paths**. The builder accepts a future replacement binary unmodified.

3. Do not replace the original boot image until the generic firmware and pathname-enabled DISK.COM are ready and tested. This test builder preserves the original 360 KiB BPB/boot sector and generates new FAT12 FAT copies, directory records and clusters. It verifies the two resulting files byte-for-byte before writing the output.

## Implementation not yet delivered

The DOS command parser, emulator interrupt/path ABI, C: FAT16 cluster-chain image adapter, generic SD: file opener, and DOS B: media invalidation still need to be implemented/tested together. The current Stage 2F image-switch command is only numeric (1–5). Do not flash or change live storage to assume otherwise.
