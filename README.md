# blitzBUS v0.7.6.1 — generator newline fix

Corrects `scripts/install_live.py` from v0.7.6. The v0.7.6 stats insertion accidentally wrote literal `\n` outside C string literals into generated `bb_microdos_pico.c`, causing GCC `stray '\'` errors. This replacement emits actual source lines, preserving `\n` only inside C format strings.

Extract this ZIP over `C:\blitzBUS` (replace `scripts\install_live.py`; the package also includes full v0.7.6 sources). Run:

```powershell
cd C:\blitzBUS
.\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180 -AutoTests
```

Do not specify `-NoBuild` or `-NoFlash`. The installer regenerates the C file before building. No edit to `C:\microDOS` original C files is necessary. Firmware behavior remains experimental and should be assessed by the diagnostic output.
