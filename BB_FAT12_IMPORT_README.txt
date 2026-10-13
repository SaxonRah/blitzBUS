blitzBUS - FAT12 file importer for DRIVE_C.IMG
================================================
The original BB_FAT16_TOOL rejects this image because the volume has 4084 data
clusters; by FAT cluster-count rules this is FAT12. The FAT16 code must not be
forced to handle this image, because the FAT entry encoding is different.

TO COPY RCXTEST.COM:
  1. Stop the Pico and make the SD image available to Windows. Do not have the
     image open/mounted read-write in another program.
  2. Put bb_fat12_import_v1.py and RCXTEST.COM into C:\blitzBUS
  3. Open Windows PowerShell:

     cd C:\blitzBUS
     python .\bb_fat12_import_v1.py info
     python .\bb_fat12_import_v1.py import .\RCXTEST.COM BENCH/RCXTEST.COM
     python .\bb_fat12_import_v1.py verify .\RCXTEST.COM BENCH/RCXTEST.COM

The image defaults to O:\BLITZBUS\DRIVE_C.IMG. Override it using
--image "D:\path\DRIVE_C.IMG" before the command if needed.

A timestamped, full byte-for-byte backup is saved in the current directory
(C:\blitzBUS by default). The writer edits a separate copy, validates the
new FAT chain and file contents, then atomically replaces the original image.

If RCXTEST.COM is already in the image and you intend to overwrite it, append
--replace to the import command.

After copying, return the SD card to the Pico and run:

     C:
     CD \BENCH
     RCXTEST

Expected RCXTEST PASS 64 / 64.

SAFETY: As with any raw disk-image editing, keep the backup until you have
confirmed the boot, BENCH directory, and other files on the actual hardware.
Only FAT12 raw superfloppy images are supported. No repartitioning or format.

Validation performed: Python 3 on synthetic 65,401-sector, 4,084-cluster
FAT12 images, import into existing BENCH, create missing BENCH, replacement,
multiple-cluster chains, duplicate FATs, exact backup and read-back SHA256.
No testing on the user's real SD image was possible here.
