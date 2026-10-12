# blitzBUS 30 MiB FAT16 read-only audit

With the Pico **OFF** and SD inserted in Windows, run:

```powershell
cd C:\blitzBUS
python .\BB_C30_AUDIT\audit_c.py O:\BLITZBUS\DRIVE_C.IMG
```

This only reads the image, checks the BPB, both FAT copies, and free cluster count. It NEVER writes to the image. Paste the output into the next conversation to identify the exact geometry/free-space issue prior to modifying firmware.

For the missing DESCENTR.EXE: preserve the extracted originals. A bound DOS/4G(W) executable is ordinarily made by a binder using the unbound image and extender, but the included 4GWBIND.EXE usage must be determined before running it. Do not rename DESCENT.UBN to DESCENTR.EXE blindly.
