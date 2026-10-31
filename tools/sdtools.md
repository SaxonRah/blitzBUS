# BB_SD_TOOLS (sd_boot r2)

Pico OFF, SD card in the PC, keep backups.

## Benchmarks on C:
A: is now BOOT.IMG from the SD, so the programs that lived on the
embedded dosbench3d.img are gone from A:. Copy them to C:\BENCH:

    python .\tools\sdtools.py import-bench C:\blitzBUS\media\dosbench3d.img O:\BLITZBUS\DRIVE_C.IMG BENCH

then on the Pico: `C:` `CD \BENCH` `T2ECPU` / `3DBENCH` (3DBENCH needs its
.HED/.PAL/.PC1/... data files in the current directory).

## Bigger C:
DOS 2.x numbers sectors with 16 bits (device request header and BPB), so
one drive tops out at 65535 x 512 bytes. grow-c rebuilds C: at up to 65520
sectors (31.99 MiB, +2.0 MiB over the 30 MiB image), same cluster size,
every file copied, original kept as DRIVE_C.BAK:

    python .\tools\sdtools.py grow-c O:\BLITZBUS\DRIVE_C.IMG --mb 32

Firmware: sd_boot r2 (this zip) reads C:'s size and BPB from the image's
boot sector instead of the hard-coded 30 MiB, so both the old and the grown
image boot. Boot line: `[bb-sd-c] DRIVE_C.IMG opened READ-WRITE 65520 sectors`.

## C: must be FAT12 for MS-DOS 2.00
FAT16 arrived with DOS 3.0. DOS 2.00 reads and writes any FAT as 12-bit, so
on the FAT16 DRIVE_C.IMG it computed the wrong free space and every write
packed 12-bit entries into the 16-bit table (check-c found 0x7E2F, 0xBE5F,
0xFE8F, 0xFFBF). make-c12 builds a FAT12 C: (8 KiB clusters, 32 MiB):

    python .\tools\sdtools.py export12 O:\BLITZBUS\BOOT.IMG COMMAND.COM .\COMMAND.COM
    python .\tools\sdtools.py make-c12 O:\BLITZBUS\DRIVE_C12.IMG --from-c O:\BLITZBUS\DRIVE_C.BAK --add .\COMMAND.COM=COMMAND.COM

`--add HOSTDIR=DOSDIR` / `--add HOSTFILE=DOSPATH` adds or replaces files;
`--from-c` also accepts a FAT12 C: (rebuild + add later); `export12` copies
a file out. Files whose old FAT16 chain is broken are listed as SKIPPED.
