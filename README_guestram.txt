BB_GUEST_RAM_V1 (extract over C:\blitzBUS, rebuild; needs blitz86 r63+):
* scripts/install_live.py: $env:BB_GUEST_KB (default 4096, range 1088..4608)
  sets total guest RAM; passes B86_RAM_BYTES to the build, sizes the PSRAM
  guest buffer to it (same 2 MiB-aligned layout); extended memory is not
  cleared (the SD overlay owns the boot memset). INT 15h 88h is logged as
  "[bb622-xms] INT15 88h -> N KiB extended" when HIMEM asks.
* src/bb_dos622_bios.inc: INT 15h AH=88h and AX=E801h report the extended
  memory; INT 15h AH=87h block move (descriptor table at ES:SI, through
  b86_host, JIT invalidation for the destination). BB_GUEST_KB=1088 restores
  the old "no extended memory" behaviour.
