Tier 2E — verification before timing
===================================
T2ECPU.COM: 256 * 32768 = 8,388,608 8086 arithmetic loop iterations.
Each outer chunk seeds AX with BP xor 12A5h, performs the fixed loop,
and XORs the result into SI. Expected final checksum = 8642h.
An incorrect checksum means DO NOT trust the timing.

The serial runner measures Windows host marker-arrival time (not the Pico's
microsecond timer). This is only a first-pass coarse wall-time measurement.
A true on-device timer requires a deliberately instrumented firmware build.

From C:\blitzBUS after extracting this ZIP into .\dos_bench\tier2e:
python .\dos_bench\tier2e\bb_tier2e_install.py --image C:\blitzBUS\media\dosbench3d.img --com C:\blitzBUS\dos_bench\tier2e\T2ECPU.COM
cmake -E touch C:\microDOS\build-pico\out\md_pico_blobs.S
cmake --build C:\microDOS\build-pico\out --target blitzbus_pico_b86_dos
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bb_live_run.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 180

Once you see A>, use Ctrl+X to close the console WITHOUT unplugging or
rebooting Pico. Then use this separate serial measurement tool:
powershell -NoProfile -ExecutionPolicy Bypass -File .\dos_bench\tier2e\bb_tier2e_measure.ps1 -Port COM5

The measure tool sends T2ECPU itself, validates CHECKSUM=8642, and reports
host-side elapsed milliseconds. If it times out, it refuses to claim timing.
