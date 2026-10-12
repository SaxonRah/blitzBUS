Tier 2D: Fixed-workload CPU benchmark for blitzBUS
================================================
Run: A>T2DCPU
Output: T2D PASS 64, 128, 192, 256 then T2D CPU CHUNKS=0100 TICKS=XXXX (HEX)
The CPU work is exactly 256 chunks x 32768 iterations = 8,388,608 iterations.
No open-ended loops waiting for BIOS tick deadlines. Reads BIOS tick before and after work only.
The four progress messages each use INT 21h AH=09, so console output overhead is included in the elapsed ticks. Clock resolution ~55ms.

Install (in C:\blitzBUS):
  Expand-Archive .\BB_TIER2D_CPU.zip .\dos_bench\tier2d -Force
  python .\dos_bench\tier2d\bb_tier2d_install.py --image C:\blitzBUS\media\dosbench3d.img --directory C:\blitzBUS\dos_bench\tier2d
  cmake -E touch C:\microDOS\build-pico\out\md_pico_blobs.S
  cmake --build C:\microDOS\build-pico\out --target blitzbus_pico_b86_dos
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180

To analyze a console log:
  python .\dos_bench\tier2d\tier2d_results.py C:\blitzBUS\logs\bb-live-YYYYMMDD-HHMMSS-console.txt

T2DCPU.COM is an independently named DOS file; T2CCPU.COM, T2CVGA.COM and 3DBENCH files stay in the image.
Backs up image as .before-tier2d.bak. Does not touch blitz86 source.
Assembly uses 8086-compatible opcodes; assembled and inspected, not tested on physical Pico.
