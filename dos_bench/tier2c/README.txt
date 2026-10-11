Tier 2C: Two DOS 8086 .COM workload benchmarks
================================================

Delivered:
  T2CCPU.COM      176 bytes   32768 iterations of add/xor/rol/dec/jnz per chunk
  T2CVGA.COM      197 bytes   32768 REP STOSB writes to A000:0000 per chunk
  bench.s         GNU as .code16 source, built using as --32 and ld -m elf_i386
  tier2c_results.py  Parse the DOS console log and compute operations/sec

Timebase is the low word of BIOS tick count at 0040:006C, read via ES.
It is NOT a direct 1 kHz PIT count. Both programs run a minimum 36 BIOS
clock ticks (~1.98 seconds). Report ticks and chunks in four-digit HEX.
The CPU code writes a checksum after each chunk to avoid treating the loop
as a no-op. The VGA benchmark enters VGA mode 13h, writes 32KiB to A000h
per chunk, then restores text mode before reporting the outcome.

DOS output examples (numbers below are ILLUSTRATIVE ONLY):
   T2C CPU CHUNKS=0020 TICKS=0024 (HEX)
   T2C VGA CHUNKS=0012 TICKS=0024 (HEX)

IMPORTANT: The binaries must be inserted into the DOS floppy image or
filesystem from which blitzBUS builds its embedded disk. Merely copying
COM files into C:\blitzBUS will not place them on the DOS A: drive.
Use the project's established disk-image/regeneration workflow.
Before modifying the disk image, make a full backup. Confirm A:DIR shows
both files after the firmware is rebuilt/flashed.

Commands in DOS:
   A>T2CCPU
   A>T2CVGA
Repeat each 3-5 times with the LCD running. For LCD paused tests, the
VGA benchmark will restore text mode and the output can be read over USB
console. Use Ctrl+P from the existing console to toggle LCD presentation;
this tests bus contention, not CPU time.

Calculate rates:
   python tier2c_results.py C:\blitzBUS\logs\bb-live-....-console.txt

Key limitations:
- CPU iteration and VGA byte-write iteration are different work units.
  Compare CPU-to-CPU and VGA-to-VGA across configurations, not CPU/VGA ratio.
- 18.2065 Hz coarse ticks produce up to one tick of timing uncertainty.
  Repeat several times and compare medians; do not infer <5% differences.
- These use the BIOS tick field, so they require that DOS firmware updates
  0040:006C correctly. Validate that elapsed TICKS is near 0024-0025.
- 8086 'REP STOSB' depends on DF=0, normally the DOS/BIOS convention. This
  binary explicitly clears DF at entry for deterministic forward writes.
- Neither program changes the scheduler or timer divisor.
- This is not a complete differential correctness test for JIT memory paths.
